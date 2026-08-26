import base64
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from models.audio_reference import AudioReference
from models.chapter import Chapter
from models.novel import Novel
from models.scene import Scene
from models.asset import Asset
from services.video.capabilities import capabilities_for
from services.video.voice_references import resolve_voice_references
from utils.enums import AssetTypeEnum


async def _scene(novel: Novel, *, narration=None) -> Scene:
    chapter = await Chapter.create(novel=novel, number=1, name="第一章", content="正文")
    return await Scene.create(
        chapter=chapter,
        sequence=1,
        prompt="@羽宁说话。",
        prompt_params={"narration": narration or []},
        duration=6,
    )


@pytest.mark.asyncio
async def test_seedance_system_voice_uses_asset_uri_and_narrator_is_conditional():
    character_voice = await AudioReference.create(
        nickname="羽宁音色", gender="女",
        audio_url="https://cdn.example.com/yuning.wav", avatar_url="",
        asset_id="asset-yuning",
    )
    narrator_voice = await AudioReference.create(
        nickname="旁白音色", gender="男",
        audio_url="https://cdn.example.com/narrator.wav", avatar_url="",
        asset_id="asset-narrator",
    )
    novel = await Novel.create(
        name="音色项目", author="作者",
        narrator_audio_reference_id=narrator_voice.id,
    )
    scene = await _scene(novel, narration=["0.0s-2.0s: 旁白（克制）：清晨降临。"])

    references = await resolve_voice_references(
        scene=scene,
        novel=novel,
        subjects=[{"name": "羽宁", "voice_reference_id": character_voice.id}],
        capabilities=capabilities_for("seedance_2"),
    )

    assert [item.url for item in references] == [
        "asset://asset-narrator", "asset://asset-yuning",
    ]
    assert references[0].kind == "narrator"
    assert references[1].subjects == ("羽宁",)


@pytest.mark.asyncio
async def test_local_upload_voice_uses_lowercase_audio_base64(monkeypatch, tmp_path):
    audio_dir = tmp_path / "audio-references"
    audio_dir.mkdir()
    audio_path = audio_dir / "voice.WAV"
    audio_path.write_bytes(b"voice-bytes")
    monkeypatch.setattr("services.video.voice_references.settings.MEDIA_PATH", str(tmp_path))
    voice = await AudioReference.create(
        nickname="本地音色", gender="女",
        audio_url="/media/audio-references/voice.WAV", avatar_url="",
        asset_id="upload-local", source="upload", duration=3,
    )
    novel = await Novel.create(name="本地音色项目", author="作者")
    scene = await _scene(novel)

    references = await resolve_voice_references(
        scene=scene,
        novel=novel,
        subjects=[{"name": "羽宁", "voice_reference_id": voice.id}],
        capabilities=capabilities_for("minimax_h3"),
    )

    assert references[0].url == (
        "data:audio/wav;base64," + base64.b64encode(b"voice-bytes").decode("ascii")
    )


@pytest.mark.asyncio
async def test_wan3_local_voice_is_prepared_for_temporary_file_upload(monkeypatch, tmp_path):
    audio_dir = tmp_path / "audio-references"
    audio_dir.mkdir()
    (audio_dir / "voice.mp3").write_bytes(b"voice-bytes")
    monkeypatch.setattr("services.video.voice_references.settings.MEDIA_PATH", str(tmp_path))
    voice = await AudioReference.create(
        nickname="本地音色", gender="女",
        audio_url="/media/audio-references/voice.mp3", avatar_url="",
        asset_id="upload-local", source="upload", duration=3,
    )
    novel = await Novel.create(name="Wan 本地音色项目", author="作者")
    scene = await _scene(novel)

    references = await resolve_voice_references(
        scene=scene,
        novel=novel,
        subjects=[{"name": "羽宁", "voice_reference_id": voice.id}],
        capabilities=capabilities_for("wan_3"),
    )

    assert references[0].url == (
        "data:audio/mp3;base64," + base64.b64encode(b"voice-bytes").decode("ascii")
    )


@pytest.mark.asyncio
async def test_wan3在oss开启时自动迁移历史本地音色并传公网url(monkeypatch, tmp_path):
    audio_dir = tmp_path / "audio-references"
    audio_dir.mkdir()
    audio_path = audio_dir / "legacy.mp3"
    audio_path.write_bytes(b"voice-bytes")
    monkeypatch.setattr("services.video.voice_references.settings.MEDIA_PATH", str(tmp_path))
    uploaded = AsyncMock()
    fake_oss = type("FakeOSS", (), {"enabled": True, "put_file": uploaded})()
    monkeypatch.setattr("services.video.voice_references.oss", fake_oss)
    monkeypatch.setattr(
        "services.video.voice_references.make_upload_key",
        lambda team_id, filename: f"uploads/{team_id}/{filename}",
    )
    monkeypatch.setattr(
        "services.video.voice_references.resolve_media_url",
        lambda raw: f"https://cdn.example.com/{raw}" if raw.startswith("uploads/") else raw,
    )
    voice = await AudioReference.create(
        nickname="历史本地音色",
        gender="男",
        audio_url="/media/audio-references/legacy.mp3",
        avatar_url="",
        asset_id="upload-legacy-local",
        source="upload",
        duration=3,
        team_id=None,
        created_by=7,
    )
    novel = await Novel.create(
        name="Wan OSS 音色项目",
        author="作者",
        team_id=3,
        created_by=7,
    )
    scene = await _scene(novel)

    references = await resolve_voice_references(
        scene=scene,
        novel=novel,
        subjects=[{"name": "羽宁", "voice_reference_id": voice.id}],
        capabilities=capabilities_for("wan_3"),
    )

    assert references[0].url == "https://cdn.example.com/uploads/3/legacy.mp3"
    uploaded.assert_awaited_once_with(
        "uploads/3/legacy.mp3",
        audio_path.resolve(),
        "audio/mpeg",
    )
    await voice.refresh_from_db()
    assert voice.audio_url == "uploads/3/legacy.mp3"
    assert voice.team_id == 3


@pytest.mark.asyncio
async def test_台词角色漏掉at标注时从分镜绑定资产兜底音色():
    voice = await AudioReference.create(
        nickname="兜底音色", gender="男",
        audio_url="https://cdn.example.com/fallback.mp3", avatar_url="",
        asset_id="asset-fallback",
    )
    novel = await Novel.create(name="兜底项目", author="作者")
    scene = await _scene(novel)
    scene.prompt = "李七夜（沉声）：我们走——"
    await scene.save(update_fields=["prompt"])
    asset = await Asset.create(
        novel=novel,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="李七夜",
        aliases=["七夜"],
        metadata={"voice_reference_id": voice.id},
    )
    await scene.assets.add(asset)

    references = await resolve_voice_references(
        scene=scene,
        novel=novel,
        subjects=[],
        capabilities=capabilities_for("seedance_2"),
    )

    assert len(references) == 1
    assert references[0].url == "asset://asset-fallback"
    assert references[0].subjects == ("李七夜",)


@pytest.mark.asyncio
async def test_兼容项目创建人历史上传的无团队音色():
    voice = await AudioReference.create(
        nickname="老头声音",
        gender="男",
        audio_url="https://cdn.example.com/old-man.mp3",
        avatar_url="",
        asset_id="upload-super-admin-legacy",
        source="upload",
        duration=5,
        team_id=None,
        created_by=7,
    )
    novel = await Novel.create(
        name="历史音色项目",
        author="作者",
        team_id=3,
        created_by=7,
    )
    scene = await _scene(novel)
    scene.prompt = "总工程师（叹气）：你还是要走？"
    await scene.save(update_fields=["prompt"])
    asset = await Asset.create(
        novel=novel,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="总工程师",
        metadata={"voice_reference_id": voice.id},
    )
    await scene.assets.add(asset)

    references = await resolve_voice_references(
        scene=scene,
        novel=novel,
        subjects=[],
        capabilities=capabilities_for("minimax_h3"),
    )

    assert len(references) == 1
    assert references[0].nickname == "老头声音"


@pytest.mark.asyncio
async def test_拒绝其他项目创建人的历史无团队音色():
    voice = await AudioReference.create(
        nickname="其他人的音色",
        gender="男",
        audio_url="https://cdn.example.com/other.mp3",
        avatar_url="",
        asset_id="upload-other-owner",
        source="upload",
        duration=5,
        team_id=None,
        created_by=8,
    )
    novel = await Novel.create(
        name="不同创建人项目",
        author="作者",
        team_id=3,
        created_by=7,
    )
    scene = await _scene(novel)

    with pytest.raises(HTTPException, match="音色不存在"):
        await resolve_voice_references(
            scene=scene,
            novel=novel,
            subjects=[{"name": "羽宁", "voice_reference_id": voice.id}],
            capabilities=capabilities_for("minimax_h3"),
        )


@pytest.mark.asyncio
async def test_20秒音频仅seedance25允许使用():
    voice = await AudioReference.create(
        nickname="20秒音色", gender="女",
        audio_url="https://cdn.example.com/voice-20s.mp3", avatar_url="",
        asset_id="upload-20s", source="upload", duration=20,
    )
    novel = await Novel.create(name="模型时长项目", author="作者")
    scene = await _scene(novel)
    subjects = [{"name": "羽宁", "voice_reference_id": voice.id}]

    with pytest.raises(HTTPException, match="2-15 秒"):
        await resolve_voice_references(
            scene=scene,
            novel=novel,
            subjects=subjects,
            capabilities=capabilities_for("seedance_2"),
        )

    references = await resolve_voice_references(
        scene=scene,
        novel=novel,
        subjects=subjects,
        capabilities=capabilities_for("seedance_2_5"),
    )
    assert references[0].duration == 20


@pytest.mark.asyncio
async def test_minimax参考音频总时长不能超过15秒():
    first = await AudioReference.create(
        nickname="音色一", gender="女",
        audio_url="https://cdn.example.com/first.mp3", avatar_url="",
        asset_id="upload-first", source="upload", duration=8,
    )
    second = await AudioReference.create(
        nickname="音色二", gender="男",
        audio_url="https://cdn.example.com/second.mp3", avatar_url="",
        asset_id="upload-second", source="upload", duration=8,
    )
    novel = await Novel.create(name="总时长项目", author="作者")
    scene = await _scene(novel)

    with pytest.raises(HTTPException, match="总时长为 16 秒"):
        await resolve_voice_references(
            scene=scene,
            novel=novel,
            subjects=[
                {"name": "羽宁", "voice_reference_id": first.id},
                {"name": "羽安", "voice_reference_id": second.id},
            ],
            capabilities=capabilities_for("minimax_h3"),
        )
