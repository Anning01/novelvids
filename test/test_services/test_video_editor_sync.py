"""Returning from storyboard generation reconciles saved edit drafts safely."""
import pytest

from auth.deps import AuthContext
from models.chapter import Chapter
from models.novel import Novel
from models.scene import Scene
from models.video import Video
from models.video_edit import ChapterEditDraft, EditorAsset
from schemas.video_edit import EditDocument, EditSave, SubtitleClip, AudioClip, EditSource
from services.video_editor.drafts import read_draft, save_draft


async def fixture():
    novel = await Novel.create(name='Editor synchronization')
    chapter = await Chapter.create(novel=novel, number=1, name='Episode', content='Fixture story')
    scenes = [await Scene.create(chapter=chapter, sequence=i+1, duration=4, prompt="Fixture shot") for i in range(7)]
    videos = [await complete(scene, 3) for scene in scenes[:3]]
    value = await read_draft(chapter.id, AuthContext())
    saved = await save_draft(chapter.id, EditSave(revision=0, document=value['document']), AuthContext())
    return chapter, scenes, videos, saved


async def complete(scene, duration):
    return await Video.create(scene=scene, model_type=1, status=3, url=f'/media/scene-{scene.id}.mp4',
                              metadata={'duration_seconds': duration})


@pytest.mark.asyncio
async def test_three_completed_shots_then_four_more_fill_existing_placeholders_and_persist():
    chapter, scenes, videos, saved = await fixture()
    original = saved['document']
    for scene in scenes[3:]:
        videos.append(await complete(scene, 5))
    loaded = await read_draft(chapter.id, AuthContext())
    clips = loaded['document']['clips']
    assert [clip['source'] for clip in clips] == [{'kind':'video', 'id':video.id} for video in videos]
    assert loaded['needs_save']
    assert [clip['duration'] for clip in clips] == [3,3,3,5,5,5,5]
    assert [clip['start'] for clip in clips] == [0,3,6,9,14,19,24]
    assert (await ChapterEditDraft.get(chapter=chapter)).document == original  # GET is read-only.
    await save_draft(chapter.id, EditSave(revision=loaded['revision'], document=loaded['document']), AuthContext())
    again = await read_draft(chapter.id, AuthContext())
    assert not again['needs_save'] and again['document'] == loaded['document']
    assert len(again['document']['clips']) == 7


@pytest.mark.asyncio
async def test_reconciliation_preserves_edits_and_pinned_versions():
    chapter, scenes, videos, saved = await fixture()
    document = EditDocument.model_validate(saved['document'])
    first = document.clips[0]
    first.name = 'Edited title'; first.trim_in = .5; first.duration = 1; first.speed = 2
    first.volume = .4; first.scale = 1.2; first.rotation = 10
    music = await EditorAsset.create(novel_id=chapter.novel_id, kind='audio', name='Music',
        media_ref='/media/music.wav', sha256='0'*64, probe={'duration': 30}, size_bytes=1)
    document.clips.extend([SubtitleClip(id='caption', type='subtitle', start=5, duration=2, text='Keep caption'),
        AudioClip(id='music', type='audio', start=0, duration=10, source=EditSource(kind='asset', id=music.id))])
    overlays = [clip.model_dump(mode='json') for clip in document.clips if clip.type != 'video']
    await save_draft(chapter.id, EditSave(revision=saved['revision'], document=document), AuthContext())
    before = (await read_draft(chapter.id, AuthContext()))['document']['clips'][0]
    retake = await complete(scenes[0], 8)
    scenes[0].metadata = {'current_video_id': retake.id}; await scenes[0].save()
    await complete(scenes[3], 2)
    loaded = await read_draft(chapter.id, AuthContext())
    assert loaded['document']['clips'][0] == before
    assert loaded['document']['clips'][0]['source']['id'] == videos[0].id
    assert loaded['document']['clips'][3]['source']['kind'] == 'video'
    assert loaded['document']['clips'][4]['source']['kind'] == 'missing'
    assert [clip for clip in loaded['document']['clips'] if clip['type'] != 'video'] == overlays


@pytest.mark.asyncio
async def test_new_scenes_are_appended_without_resurrecting_manually_removed_clips():
    chapter, scenes, _, saved = await fixture()
    document = EditDocument.model_validate(saved['document'])
    document.clips = document.clips[1:]
    await save_draft(chapter.id, EditSave(revision=saved['revision'], document=document), AuthContext())
    new_scene = await Scene.create(chapter=chapter, sequence=8, duration=6, prompt="New shot")
    video = await complete(new_scene, 6)
    loaded = await read_draft(chapter.id, AuthContext())
    clips = loaded['document']['clips']
    assert len(clips) == 7
    assert f'scene-{scenes[0].id}' not in {clip['id'] for clip in clips}
    assert clips[-1]['source'] == {'kind':'video', 'id':video.id}
    assert loaded['needs_save']


@pytest.mark.asyncio
async def test_failed_generation_remains_a_placeholder():
    chapter, scenes, _, _ = await fixture()
    await Video.create(scene=scenes[3], model_type=1, status=4, url=None)
    loaded = await read_draft(chapter.id, AuthContext())
    assert not loaded['needs_save']
    assert loaded['document']['clips'][3]['source'] == {'kind':'missing', 'id':scenes[3].id}
