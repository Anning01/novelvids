import asyncio
import io
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock
import pytest
from fastapi import HTTPException, UploadFile
from pydantic import ValidationError
from tortoise import Tortoise
from auth.deps import AuthContext
from models.chapter import Chapter
from models.novel import Novel
from models.scene import Scene
from models.video import Video
from models.video_edit import ChapterEditDraft
from models.ai_task import AiTask
from schemas.video_edit import EditDocument, EditSave
from services.video_editor.drafts import read_draft, save_draft
from services.video_editor.assets import editor_storage
from services.video_editor.sources import EditSources
from services.video_editor.exports import submit_export, editor_export_worker, describe_export
from services.video_editor.render import wrap_subtitle


def ffmpeg(*args):
    return subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-y', *map(str, args)], check=True,
                          capture_output=True, timeout=40).stdout


@pytest.fixture
def media(tmp_path, monkeypatch):
    monkeypatch.setattr('config.settings.MEDIA_PATH', str(tmp_path/'media'))
    monkeypatch.setattr('config.settings.CHAPTER_EXPORT_PATH', str(tmp_path/'private'))
    root = tmp_path/'media'; root.mkdir()
    video = root/'red.mp4'
    ffmpeg('-f','lavfi','-i','color=c=red:s=320x180:r=24:d=2','-f','lavfi','-i',
           'sine=frequency=300:sample_rate=48000:duration=2','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',video)
    audio = tmp_path/'music.wav'
    ffmpeg('-f','lavfi','-i','sine=frequency=1000:sample_rate=48000:duration=2',audio)
    sticker = tmp_path/'sticker.png'
    ffmpeg('-f','lavfi','-i','color=c=yellow:s=16x16','-frames:v','1',sticker)
    return video, audio, sticker


async def project():
    novel = await Novel.create(name='Editor project', aspect_ratio='16:9')
    chapter = await Chapter.create(novel=novel, number=1, name='First', content='Story')
    scene = await Scene.create(chapter=chapter, sequence=1, prompt='Do not rewrite', duration=2)
    video = await Video.create(scene=scene, model_type=1, status=3, url='/media/red.mp4', metadata={'duration':2})
    return novel, chapter, scene, video


def video_clip(video_id, **extra):
    return {'id':'v1','type':'video','name':'First shot','start':0,'duration':2,
            'source':{'kind':'video','id':video_id}, **extra}


def test_typed_document_rejects_paths_duplicate_ids_overlap_and_nonfinite_numbers():
    valid = video_clip(1)
    for document in [
        {'clips': [{**valid, 'source': {'kind':'video','id':1,'path':'/etc/passwd'}}]},
        {'clips':[valid,valid]}, {'clips':[valid,{**valid,'id':'v2','start':1}]},
        {'clips':[{**valid,'speed':float('nan')}]}, {'width':3840,'height':3840},
        {'clips':[{'id':'s','type':'subtitle','start':0,'duration':1,'text':'x','color':'red;movie=x'}]},
    ]:
        with pytest.raises(ValidationError): EditDocument.model_validate(document)
    snap = EditDocument(clips=[{**valid, 'start':.1, 'duration':.1}])
    assert snap.clips[0].start == 2/24 and snap.clips[0].duration == 2/24


@pytest.mark.asyncio
async def test_lazy_draft_save_conflict_and_scene_history_remain_untouched():
    novel, chapter, scene, video = await project()
    ctx = AuthContext()
    value = await read_draft(chapter.id,ctx)
    assert value['revision']==0 and not await ChapterEditDraft.all().exists()
    assert value['document']['clips'][0]['source']=={'kind':'video','id':video.id}
    document = EditDocument.model_validate(value['document'])
    saved = await save_draft(chapter.id,EditSave(revision=0,document=document),ctx)
    assert saved['revision']==1
    document.clips[0].volume=.2
    with pytest.raises(HTTPException) as error:
        await save_draft(chapter.id,EditSave(revision=0,document=document),ctx)
    assert error.value.status_code==409
    await scene.refresh_from_db()
    assert scene.prompt=='Do not rewrite' and not scene.metadata
    assert await Video.all().count()==1 and not await AiTask.all().exists()
    assert (await read_draft(chapter.id,ctx))['document']['clips'][0]['volume']==1


@pytest.mark.asyncio
async def test_new_drafts_inherit_project_output_dimensions_without_ai_enhancement():
    novel, chapter, _, _ = await project()
    novel.resolution, novel.aspect_ratio = '480p', '9:16'
    await novel.save(update_fields=['resolution','aspect_ratio'])
    value=await read_draft(chapter.id,AuthContext())
    assert value['document']['width']==480 and value['document']['height']==854
    assert not await AiTask.all().exists()


@pytest.mark.asyncio
async def test_source_ids_are_scoped_and_missing_shots_block_export():
    novel, chapter, scene, video=await project()
    other=await Novel.create(name='Other')
    foreign=await Chapter.create(novel=other,number=1,name='Other',content='')
    foreign_scene=await Scene.create(chapter=foreign,sequence=1,duration=2)
    foreign_video=await Video.create(scene=foreign_scene,model_type=1,status=3,url='/media/secret.mp4')
    with pytest.raises(HTTPException) as error:
        await save_draft(chapter.id,EditSave(revision=0,document=EditDocument(clips=[video_clip(foreign_video.id)])),AuthContext())
    assert error.value.status_code==404
    missing=EditDocument(clips=[{**video_clip(video.id),'source':{'kind':'missing','id':scene.id}}])
    await save_draft(chapter.id,EditSave(revision=0,document=missing),AuthContext())
    with pytest.raises(HTTPException) as error:
        await submit_export(chapter.id,1,AuthContext())
    assert error.value.status_code==422 and not await AiTask.all().exists()


@pytest.mark.asyncio
async def test_actual_upload_render_and_idempotent_export_have_no_model_billing(media, monkeypatch):
    import array, math
    from models.usage_record import ModelUsageRecord
    novel,chapter,scene,video=await project()
    music=await editor_storage.import_file(chapter,UploadFile(filename='music.wav',file=io.BytesIO(media[1].read_bytes())),'audio',AuthContext())
    sticker=await editor_storage.import_file(chapter,UploadFile(filename='sticker.png',file=io.BytesIO(media[2].read_bytes())),'sticker',AuthContext())
    document=EditDocument(width=320,height=180,clips=[
        video_clip(video.id,volume=0),
        {'id':'a','type':'audio','name':'Music','source':music['source'],'start':.5,'duration':1.5,'volume':.5},
        {'id':'s','type':'subtitle','start':.5,'duration':1,'text':"修仙 Hello %{text}",'font_size':90},
        {'id':'i','type':'sticker','source':sticker['source'],'start':.5,'duration':1,'x':75,'y':25},
    ])
    await save_draft(chapter.id,EditSave(revision=0,document=document),AuthContext())
    row=await submit_export(chapter.id,1,AuthContext())
    replay=await submit_export(chapter.id,1,AuthContext())
    assert replay.id==row.id and await AiTask.all().count()==1
    await asyncio.gather(editor_export_worker.execute(row.id),editor_export_worker.execute(row.id))
    result=await describe_export(row)
    task=await AiTask.get(id=row.task_id)
    assert task.status==3,task.error_message
    await row.refresh_from_db()
    assert row.output_probe['width']==320 and row.output_probe['height']==180
    assert abs(float(row.output_probe['duration'])-2)<.1
    from services.video_enhancement.media import export_media
    output=export_media.local_path(row.media_ref)
    def color(at):
        data=ffmpeg('-ss',at,'-i',output,'-frames:v','1','-vf','crop=8:8:236:40','-pix_fmt','rgb24','-f','rawvideo','-')
        return [sum(data[i::3])/len(data[i::3]) for i in range(3)]
    before,during=color(.1),color(.8)
    assert before[0]>180 and before[1]<80
    assert during[0]>180 and during[1]>180  # Yellow sticker actually reaches the encoded video.
    data=ffmpeg('-i',output,'-vn','-f','f32le','-ac','1','-ar','8000','-')
    samples=array.array('f',data)
    def rms(begin,end): return math.sqrt(sum(v*v for v in samples[int(begin*8000):int(end*8000)])/int((end-begin)*8000))
    assert rms(.1,.3)<.002 and rms(.8,1.0)>.01
    assert not await ModelUsageRecord.all().exists()
    assert media[0].is_file() and (await Scene.get(id=scene.id)).prompt=='Do not rewrite'
    assert (await submit_export(chapter.id,1,AuthContext())).id==row.id


@pytest.mark.asyncio
async def test_cancelled_job_cannot_publish_and_expired_leases_recover(media):
    from datetime import datetime,timedelta,timezone
    from models.chapter_export import ChapterExport
    _,chapter,_,video=await project()
    await save_draft(chapter.id,EditSave(revision=0,document=EditDocument(clips=[video_clip(video.id)])),AuthContext())
    row=await submit_export(chapter.id,1,AuthContext())
    await AiTask.filter(id=row.task_id).update(status=5)
    await editor_export_worker.execute(row.id)
    assert not (await ChapterExport.get(id=row.id)).media_ref
    await submit_export(chapter.id,1,AuthContext())
    await ChapterExport.filter(id=row.id).update(collection_lease_until=datetime.now(timezone.utc)-timedelta(seconds=1))
    await editor_export_worker.execute(row.id)
    assert (await AiTask.get(id=row.task_id)).status==3


@pytest.mark.asyncio
async def test_multi_clip_export_has_continuous_audio_timestamps_and_expected_duration(media):
    _, chapter, _, video = await project()
    document=EditDocument(width=320,height=180,clips=[video_clip(video.id),
        video_clip(video.id,id='v2',start=2),
        {'id':'sub','type':'subtitle','start':0,'duration':4,'text':'Two clips / 两个镜头'}])
    await save_draft(chapter.id,EditSave(revision=0,document=document),AuthContext())
    row=await submit_export(chapter.id,1,AuthContext())
    await editor_export_worker.execute(row.id)
    task=await AiTask.get(id=row.task_id)
    assert task.status==3, task.error_message
    await row.refresh_from_db()
    assert abs(float(row.output_probe['duration'])-4)<.1
    from services.video_enhancement.media import export_media
    path=export_media.local_path(row.media_ref)
    ffmpeg('-xerror','-i',path,'-f','null','-')


@pytest.mark.asyncio
async def test_cover_then_zoom_out_matches_preview_framing(media):
    _,chapter,_,video=await project()
    document=EditDocument(width=180,height=320,clips=[video_clip(video.id,fit='cover',scale=.5)])
    await save_draft(chapter.id,EditSave(revision=0,document=document),AuthContext())
    row=await submit_export(chapter.id,1,AuthContext())
    await editor_export_worker.execute(row.id)
    assert (await AiTask.get(id=row.task_id)).status==3
    await row.refresh_from_db()
    from services.video_enhancement.media import export_media
    output=export_media.local_path(row.media_ref)
    def pixel(x):
        data=ffmpeg('-ss','0.5','-i',output,'-frames:v','1','-vf',f'crop=4:4:{x}:158','-pix_fmt','rgb24','-f','rawvideo','-')
        return [sum(data[i::3])/len(data[i::3]) for i in range(3)]
    assert max(pixel(10))<20  # A shrunken viewport has black padding at the left.
    assert pixel(88)[0]>180


def test_subtitle_wrap_is_plain_text_and_preserves_explicit_lines():
    assert wrap_subtitle('你好世界\nHello',100,20)=='你好世界\nHello'
    assert wrap_subtitle('你好世界你好',100,20)=='你好世界\n你好'


@pytest.mark.asyncio
async def test_editor_schema_is_additive_repeatable_and_keeps_existing_rows():
    from services.schema_compat import ensure_video_editor_schema
    _,chapter,_,_=await project()
    draft=await ChapterEditDraft.create(chapter=chapter,document={'version':1,'clips':[]})
    await ensure_video_editor_schema(); await ensure_video_editor_schema()
    assert (await ChapterEditDraft.get(id=draft.id)).document=={'version':1,'clips':[]}
    assert await Scene.all().count()==1 and await Video.all().count()==1


@pytest.mark.asyncio
async def test_worker_discovers_queued_jobs_and_keeps_running_after_user_cancels(monkeypatch):
    from services.video_editor.exports import EditorExportWorker
    from controllers.ai_task import ai_task_controller
    _,chapter,_,video=await project()
    await save_draft(chapter.id,EditSave(revision=0,document=EditDocument(clips=[video_clip(video.id)])),AuthContext())
    row=await submit_export(chapter.id,1,AuthContext())
    worker=EditorExportWorker()
    entered=asyncio.Event()
    async def render(_row,cancelled,progress):
        entered.set()
        while not await cancelled(): await asyncio.sleep(.01)
        raise asyncio.CancelledError
    monkeypatch.setattr(worker,'render',render)
    await worker.start()
    try:
        await asyncio.wait_for(entered.wait(),3)
        await ai_task_controller.cancel(row.task_id)
        await asyncio.sleep(1.2)
        assert not worker.loop_task.done()
        assert (await AiTask.get(id=row.task_id)).status==5
    finally:
        await worker.stop()
