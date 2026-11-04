"""Unit and integration tests for Volc SeedASR 2.0 and video editor subtitle recognition."""
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest

from models.config import AiModelConfig
from models.chapter import Chapter
from models.novel import Novel
from models.video_edit import ChapterEditDraft
from schemas.video_edit import EditDocument, SubtitleClip, VideoClip, AudioClip
from services.audio_recognition.volc_seedasr import VolcSeedAsrClient
from services.billing.catalog import ASR_PRICING, pricing_for
from services.billing.pricing import compute_asr_cost
from services.billing.recorder import billing_recorder
from services.video_editor.recognition import recognize_and_apply_subtitles
from utils.enums import AiTaskTypeEnum


def test_compute_asr_cost():
    pricing = {
        "type": "asr",
        "currency": "CNY",
        "billing_unit": "minute",
        "price_per_minute": 0.015,
    }
    # 60 秒（1 分钟）= 0.015 元
    cost_60s = compute_asr_cost(60.0, pricing)
    assert cost_60s == Decimal("0.015000")

    # 30 秒（0.5 分钟）= 0.0075 元
    cost_30s = compute_asr_cost(30.0, pricing)
    assert cost_30s == Decimal("0.007500")

    # 120 秒（2 分钟）= 0.030 元
    cost_120s = compute_asr_cost(120.0, pricing)
    assert cost_120s == Decimal("0.030000")

    # 带折扣（50% 折扣）
    discount_pricing = {**pricing, "discount": 0.5}
    cost_discount = compute_asr_cost(60.0, discount_pricing)
    assert cost_discount == Decimal("0.007500")

    # 非 ASR 配置返回 0
    assert compute_asr_cost(60.0, {"type": "text"}) == Decimal("0")


def test_asr_pricing_catalog():
    assert "volc.seedasr.auc" in ASR_PRICING
    assert ASR_PRICING["volc.seedasr.auc"]["price_per_minute"] == 0.015

    dummy_config = MagicMock()
    dummy_config.image_model_type = None
    dummy_config.video_model_type = None
    dummy_config.task_type = AiTaskTypeEnum.audio_recognition.value
    dummy_config.task_types = [AiTaskTypeEnum.audio_recognition.value]
    dummy_config.model = "volc.seedasr.auc"

    matched = pricing_for(dummy_config)
    assert matched is not None
    assert matched["price_per_minute"] == 0.015


def test_volc_client_key_parsing():
    c1 = VolcSeedAsrClient(api_key="my_app:my_token")
    assert c1._parse_keys() == ("my_app", "my_token")
    headers1 = c1._build_headers("req-1")
    assert headers1["X-Api-App-Key"] == "my_app"
    assert headers1["X-Api-Access-Key"] == "my_token"
    assert "X-Api-Key" not in headers1
    assert headers1["X-Api-Resource-Id"] == "volc.seedasr.auc"

    c2 = VolcSeedAsrClient(api_key="app2;tok2")
    assert c2._parse_keys() == ("app2", "tok2")

    c3 = VolcSeedAsrClient(api_key="standalone_token")
    assert c3._parse_keys() == ("", "standalone_token")
    headers3 = c3._build_headers("req-3")
    assert "X-Api-App-Key" not in headers3
    assert headers3["X-Api-Key"] == "standalone_token"


@pytest.mark.asyncio
async def test_volc_client_recognize_success():
    client = VolcSeedAsrClient(api_key="test_key", poll_interval=0.01)

    submit_response = MagicMock(status_code=200)
    submit_response.headers = {"X-Api-Status-Code": "20000000"}
    submit_response.text = ""

    query_response_1 = MagicMock(status_code=200)
    query_response_1.headers = {"X-Api-Status-Code": "20000001"}

    query_response_2 = MagicMock(status_code=200)
    query_response_2.headers = {"X-Api-Status-Code": "20000000"}
    query_response_2.text = '{"result": {"utterances": [{"start_time": 100, "end_time": 1500, "text": "你好世界"}]}}'
    query_response_2.json.return_value = {
        "result": {
            "utterances": [
                {"start_time": 100, "end_time": 1500, "text": "你好世界"}
            ]
        }
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = [submit_response, query_response_1, query_response_2]
        utterances = await client.recognize(audio_bytes=b"fake-audio-bytes")

    assert len(utterances) == 1
    assert utterances[0]["text"] == "你好世界"
    assert utterances[0]["start_time"] == 100
    assert utterances[0]["end_time"] == 1500


@pytest.mark.asyncio
async def test_volc_client_submit_error():
    client = VolcSeedAsrClient(api_key="test_key")
    submit_response = MagicMock(status_code=400)
    submit_response.headers = {"X-Api-Status-Code": "40000001", "X-Api-Message": "Invalid key"}
    submit_response.text = "Invalid key"

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = submit_response
        with pytest.raises(RuntimeError, match="提交语音识别任务失败"):
            await client.recognize(audio_bytes=b"fake-audio")


@pytest.mark.asyncio
async def test_record_asr_billing():
    novel = await Novel.create(name="Novel ASR", description="test")
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.audio_recognition.value,
        name="test-seedasr",
        model="volc.seedasr.auc",
        api_key="key",
        base_url="https://openspeech.bytedance.com/api/v3/auc/bigmodel",
        is_active=True,
        pricing={
            "type": "asr",
            "currency": "CNY",
            "billing_unit": "minute",
            "price_per_minute": 0.015,
        },
    )

    record = await billing_recorder.record_asr(
        novel_id=novel.id,
        seconds=120.0,
        model_config_id=config.id,
    )
    assert record is not None
    assert record.billing_type == "asr"
    assert record.task_type == AiTaskTypeEnum.audio_recognition.value
    assert record.cost == Decimal("0.030000")
    assert record.usage["duration_seconds"] == 120.0
    assert record.usage["minutes"] == 2.0


@pytest.mark.asyncio
async def test_recognize_and_apply_subtitles_flow():
    novel = await Novel.create(name="Novel Subtitle", description="test")
    chapter = await Chapter.create(novel_id=novel.id, name="Chapter 1", number=1, content="content")
    await AiModelConfig.create(
        task_type=AiTaskTypeEnum.audio_recognition.value,
        name="test-asr-active",
        model="volc.seedasr.auc",
        api_key="test-key",
        base_url="https://openspeech.bytedance.com/api/v3/auc/bigmodel",
        is_active=True,
        pricing={
            "type": "asr",
            "currency": "CNY",
            "billing_unit": "minute",
            "price_per_minute": 0.015,
        },
    )

    # 构造带有旧字幕的时间线草稿
    old_sub = SubtitleClip(
        id="old-sub-1",
        type="subtitle",
        name="",
        start=0.0,
        duration=2.0,
        text="旧字幕待清空",
    )
    video_clip = VideoClip(
        id="v-1",
        type="video",
        name="分镜 1",
        source={"kind": "video", "id": 101},
        start=0.0,
        duration=5.0,
        trim_in=0.0,
        speed=1.0,
        volume=1.0,
    )
    initial_doc = EditDocument(
        width=1280,
        height=720,
        fps=24,
        clips=[video_clip, old_sub],
    )
    await ChapterEditDraft.create(
        chapter_id=chapter.id,
        document=initial_doc.model_dump(mode="json"),
        revision=1,
    )

    mock_auth = MagicMock()
    mock_auth.team_id = None
    mock_auth.user = None
    mock_auth.role = "admin"

    mock_utterances = [
        {"start_time": 200, "end_time": 1800, "text": "大家好今天给大家介绍一款软件。"},
        {"start_time": 2100, "end_time": 4500, "text": "如果你平时有在做短视频，"},
    ]

    with patch("services.video_editor.recognition.extract_timeline_audio", new_callable=AsyncMock) as mock_extract, \
         patch("services.video_editor.recognition.VolcSeedAsrClient.recognize", new_callable=AsyncMock) as mock_rec, \
         patch("services.video_editor.recognition.chapter_scope", new_callable=AsyncMock) as mock_scope:

        mock_scope.return_value = chapter
        mock_extract.return_value = (b"mock-audio", 5.0)
        mock_rec.return_value = mock_utterances

        res = await recognize_and_apply_subtitles(chapter.id, mock_auth)
        mock_rec.assert_awaited_once_with(audio_bytes=b"mock-audio", format="mp3")

    assert res["subtitles_created"] == 2
    assert res["revision"] == 1

    # 验证新文档：旧字幕被清除，新字幕已生效且清洗标点
    clips = res["document"]["clips"]
    subtitles = [c for c in clips if c["type"] == "subtitle"]
    videos = [c for c in clips if c["type"] == "video"]

    assert len(videos) == 1
    assert len(subtitles) == 2
    assert subtitles[0]["text"] == "大家好今天给大家介绍一款软件"
    assert subtitles[0]["start"] == 0.2
    assert subtitles[0]["duration"] == 1.6
    assert subtitles[1]["text"] == "如果你平时有在做短视频"
    assert subtitles[1]["start"] == 2.1
    assert subtitles[1]["duration"] == 2.4

    # 验证数据库中草稿已保存
    saved_draft = await ChapterEditDraft.get(chapter_id=chapter.id)
    assert saved_draft.revision == 1
    assert [c["id"] for c in saved_draft.document["clips"] if c["type"] == "subtitle"] == ["old-sub-1"]


@pytest.mark.asyncio
async def test_asr_model_config_schema_validation():
    from schemas.config import AiModelConfigOut

    config = await AiModelConfig.create(
        name="volc-seedasr-2.0",
        task_type=AiTaskTypeEnum.audio_recognition.value,
        task_types=[AiTaskTypeEnum.audio_recognition.value],
        base_url="https://openspeech.bytedance.com",
        api_key="test-key",
        model="volc.seedasr.auc",
        api_protocol="volcengine_openspeech",
        concurrency=5,
        is_active=True,
    )
    out = AiModelConfigOut.model_validate(config)
    assert out.api_protocol == "volcengine_openspeech"
    assert out.model == "volc.seedasr.auc"


@pytest.mark.asyncio
async def test_asr_resolution_does_not_use_another_teams_key():
    from fastapi import HTTPException
    from services.video_editor.recognition import _resolve_asr_config
    await AiModelConfig.create(name='Other private',base_url='https://example.test',task_type=9,task_types=[9],api_key='other-test-key',model='volc.seedasr.auc',scope='team',team_id=999,is_active=True)
    with pytest.raises(HTTPException):
        await _resolve_asr_config(None)


@pytest.mark.asyncio
async def test_asr_query_uses_the_submitted_task_id():
    submit=httpx.Response(200,headers={'X-Api-Status-Code':'20000000'},json={'task_id':'assigned-id'})
    done=httpx.Response(200,headers={'X-Api-Status-Code':'20000000'},json={'result':{'utterances':[]}})
    with patch('httpx.AsyncClient.post',new_callable=AsyncMock) as post:
        post.side_effect=[submit,done]
        await VolcSeedAsrClient('test-key',poll_interval=0).recognize(audio_bytes=b'audio')
        assert post.call_args_list[1].kwargs['headers']['X-Api-Request-Id']=='assigned-id'


@pytest.mark.asyncio
async def test_asr_provider_error_is_redacted(caplog):
    response=httpx.Response(400,headers={'X-Api-Status-Code':'45000001','X-Api-Message':'secret-from-provider'},text='secret-from-provider')
    with patch('httpx.AsyncClient.post',new_callable=AsyncMock,return_value=response):
        with pytest.raises(RuntimeError) as error:
            await VolcSeedAsrClient('test-key').recognize(audio_bytes=b'audio')
    assert 'secret-from-provider' not in str(error.value)
    assert 'secret-from-provider' not in caplog.text

@pytest.mark.asyncio
async def test_extracts_speed_adjusted_audio_and_silent_video(tmp_path, monkeypatch):
    import subprocess
    from test.test_services.test_video_editor import ffmpeg, project
    from models.video_edit import EditorAsset
    from services.audio_recognition.extractor import extract_timeline_audio
    root=tmp_path/'media'; root.mkdir()
    monkeypatch.setattr('config.settings.MEDIA_PATH',str(root))
    monkeypatch.setattr('config.settings.CHAPTER_EXPORT_PATH',str(tmp_path/'private'))
    ffmpeg('-f','lavfi','-i','color=c=red:s=320x180:r=24:d=2','-f','lavfi','-i','sine=frequency=300:sample_rate=48000:duration=1','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',root/'red.mp4')
    ffmpeg('-f','lavfi','-i','color=c=blue:s=320x180:r=24:d=2','-c:v','libx264','-pix_fmt','yuv420p',root/'silent.mp4')
    novel,chapter,_,video=await project()
    silent=await EditorAsset.create(novel=novel,kind='video',name='Silent',media_ref='/media/silent.mp4',sha256='',probe={'duration':2})
    doc=EditDocument(clips=[VideoClip(id='v',type='video',source={'kind':'video','id':video.id},start=0,duration=1,speed=2),VideoClip(id='silent',type='video',source={'kind':'asset','id':silent.id},start=1,duration=2)])
    # A long BGM referencing an absent source must never be resolved or mixed into ASR.
    doc.clips.append(AudioClip(id='bgm',type='audio',source={'kind':'asset','id':999999},start=0,duration=60,volume=10,loop=True))
    data,duration=await extract_timeline_audio(doc,chapter.id,novel.id)
    path=tmp_path/'timeline.mp3';path.write_bytes(data)
    import json
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(path)]))
    assert duration==3
    assert abs(float(probe['format']['duration'])-3)<.15
    assert probe['streams'][0]['sample_rate']=='16000'
    assert probe['streams'][0]['channels']==1
