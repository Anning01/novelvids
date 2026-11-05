from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from auth.deps import AuthContext
from controllers.finished_episode import list_finished, versions, publish, feature
from models.chapter_export import ChapterExport
from models.ai_task import AiTask
from models.chapter import Chapter
from models.novel import Novel
from services.video_editor.finished_media import get_cover, save_cover
from services.video_enhancement.media import export_media
from test.test_services.test_video_editor import ffmpeg, media


async def finished(chapter, revision=1, seconds=3, status=3, ref='/media/exports/1/edited.mp4'):
    task = await AiTask.create(task_type=4, status=status, stage='completed', finished_at=datetime.now(timezone.utc),
                               request_params={'operation': 'editor_render'})
    return await ChapterExport.create(
        novel_id=chapter.novel_id, chapter_id=chapter.id, team_id=chapter.novel_id,
        identity_key=f'{chapter.id}-{revision}', source_version='x', task=task,
        recipe={'kind':'editor_render','revision':revision}, output_probe={'duration':seconds,'width':320,'height':180,'fps':24},
        media_ref=ref, collection_complete=True,
    )


@pytest.mark.asyncio
async def test_library_keeps_versions_and_publishing_points_at_one_export():
    project = await Novel.create(name='Finished project')
    chapter = await Chapter.create(novel=project,number=1,name='First',content='')
    first = await finished(chapter)
    second = await finished(chapter,revision=2)
    result = await list_finished(AuthContext(),'team',None,1,20)
    assert result['total']==1
    assert result['items'][0].version.id==second.id
    assert [v.revision for v in await versions(chapter.id,AuthContext())]==[2,1]
    await publish(chapter.id,first.id,AuthContext())
    await feature(chapter.id,first.id,True,AuthContext())
    assert (await list_finished(AuthContext(),'featured',None,1,20))['items'][0].version.id==first.id
    await publish(chapter.id,second.id,AuthContext(),first.id)
    assert (await list_finished(AuthContext(),'featured',None,1,20))['total']==0
    assert (await list_finished(AuthContext(),'published',None,1,20))['items'][0].version.id==second.id
    await publish(chapter.id,None,AuthContext(),second.id)
    assert (await list_finished(AuthContext(),'published',None,1,20))['total']==0


@pytest.mark.asyncio
async def test_failed_or_empty_exports_do_not_finish_an_episode():
    project=await Novel.create(name='Incomplete')
    chapter=await Chapter.create(novel=project,number=1,name='First',content='')
    await finished(chapter,status=4)
    await finished(chapter,revision=2,ref='')
    assert (await list_finished(AuthContext(),'team',None,1,20))['total']==0


@pytest.mark.asyncio
async def test_cover_is_saved_from_first_frame_and_existing_export_can_reuse_it(tmp_path,monkeypatch):
    monkeypatch.setattr('config.settings.MEDIA_PATH',str(tmp_path/'media'))
    monkeypatch.setattr('config.settings.CHAPTER_EXPORT_PATH',str(tmp_path/'private'))
    source=tmp_path/'source.mp4'
    # Red is the first frame. The second segment is blue.
    ffmpeg('-f','lavfi','-i','color=c=red:s=320x180:r=24:d=1','-f','lavfi','-i','color=c=blue:s=320x180:r=24:d=1',
           '-filter_complex','[0:v][1:v]concat=n=2:v=1:a=0[v]','-map','[v]','-c:v','libx264','-pix_fmt','yuv420p',source)
    project=await Novel.create(name='Cover')
    chapter=await Chapter.create(novel=project,number=1,name='First',content='')
    row=await finished(chapter)
    row.media_ref=export_media.ref(row,'edited')
    await export_media.store(row.media_ref,source)
    cover=await get_cover(row)
    pixels=ffmpeg('-i',cover,'-vf','scale=1:1','-f','rawvideo','-pix_fmt','rgb24','-')
    assert pixels[0]>200 and pixels[2]<30
    assert cover.is_relative_to(tmp_path/'private')
    spy=AsyncMock()
    monkeypatch.setattr('services.video_editor.finished_media.save_cover',spy)
    assert await get_cover(row)==cover
    spy.assert_not_awaited()


@pytest.mark.asyncio
async def test_completion_counts_each_chapter_once_using_the_latest_successful_render():
    from services.project_overview import project_overview
    project=await Novel.create(name='Versions')
    first=await Chapter.create(novel=project,number=1,name='One',content='')
    second=await Chapter.create(novel=project,number=2,name='Two',content='')
    await finished(first,seconds=3)
    await finished(first,revision=2,seconds=5)
    await finished(second,seconds=8)
    result=await project_overview()
    assert result.items[0].production.completed_episode_count==2
    assert result.items[0].production.finished_seconds==13
    assert result.summary.finished_seconds==13


@pytest.mark.asyncio
async def test_finished_schema_initialization_is_additive_and_repeatable():
    from tortoise import Tortoise
    from services.schema_compat import ensure_video_editor_schema
    from models.finished_episode import FinishedEpisodePublication
    project=await Novel.create(name='Schema')
    chapter=await Chapter.create(novel=project,number=1,name='One',content='')
    export=await finished(chapter)
    await publish(chapter.id,export.id,AuthContext())
    before=(await FinishedEpisodePublication.get(chapter_id=chapter.id)).export_id
    for _ in range(2):
        await ensure_video_editor_schema()
        await Tortoise.generate_schemas(safe=True)
        assert (await FinishedEpisodePublication.get(chapter_id=chapter.id)).export_id==before
        assert (await ChapterExport.get(id=export.id)).recipe['revision']==1


@pytest.mark.asyncio
async def test_cover_failure_keeps_export_incomplete_until_retry(media,monkeypatch):
    from auth.deps import AuthContext
    from schemas.video_edit import EditDocument, EditSave
    from services.video_editor.drafts import save_draft
    from services.video_editor.exports import submit_export, editor_export_worker
    from test.test_services.test_video_editor import project, video_clip
    _,chapter,_,video=await project()
    await save_draft(chapter.id,EditSave(revision=0,document=EditDocument(clips=[video_clip(video.id)])),AuthContext())
    row=await submit_export(chapter.id,1,AuthContext())
    with monkeypatch.context() as patch:
        patch.setattr('services.video_editor.exports.save_cover',AsyncMock(side_effect=ValueError('Cover failed')))
        await editor_export_worker.execute(row.id)
    await row.refresh_from_db()
    assert not row.collection_complete and not row.media_ref
    assert (await AiTask.get(id=row.task_id)).status==4
    assert (await list_finished(AuthContext(),'team',None,1,20))['total']==0
    assert (await submit_export(chapter.id,1,AuthContext())).id==row.id
    await editor_export_worker.execute(row.id)
    await row.refresh_from_db()
    assert row.collection_complete and (await get_cover(row)).is_file()
    assert (await list_finished(AuthContext(),'team',None,1,20))['total']==1
