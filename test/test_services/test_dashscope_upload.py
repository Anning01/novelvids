import base64

import httpx
import pytest

from services.video.dashscope_upload import DashScopeTemporaryFileUploader


@pytest.mark.asyncio
async def test_uploads_data_uri_with_model_bound_policy_and_reuses_result(monkeypatch):
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            assert str(request.url) == (
                "https://dashscope.aliyuncs.com/api/v1/uploads"
                "?action=getPolicy&model=wan3.0-video"
            )
            assert request.headers["authorization"] == "Bearer dashscope-secret"
            return httpx.Response(200, json={
                "data": {
                    "policy": "policy-value",
                    "signature": "signature-value",
                    "upload_dir": "dashscope-instant/account/job",
                    "upload_host": "https://dashscope-file-test.oss-cn-beijing.aliyuncs.com",
                    "max_file_size_mb": 100,
                    "oss_access_key_id": "temporary-access-key",
                    "x_oss_object_acl": "private",
                    "x_oss_forbid_overwrite": "true",
                },
            })
        assert str(request.url) == "https://dashscope-file-test.oss-cn-beijing.aliyuncs.com"
        body = await request.aread()
        assert b"voice-bytes" in body
        assert b'temporary-access-key' in body
        assert b'name="file"' in body
        return httpx.Response(200)

    real_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr("services.video.dashscope_upload.httpx.AsyncClient", client_factory)
    source = "data:audio/mp3;base64," + base64.b64encode(b"voice-bytes").decode("ascii")
    uploader = DashScopeTemporaryFileUploader(
        api_key="dashscope-secret",
        model="wan3.0-video",
    )

    first = await uploader.resolve(source)
    second = await uploader.resolve(source)

    assert first.startswith("oss://dashscope-instant/account/job/")
    assert first.endswith(".mp3")
    assert second == first
    assert len(requests) == 2
