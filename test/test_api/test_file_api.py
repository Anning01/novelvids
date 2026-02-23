import pytest
import os
import tempfile
import shutil
from httpx import AsyncClient
from config import settings


@pytest.fixture(autouse=True)
def _ensure_media_dir(tmp_path):
    """使用临时目录替代真实 MEDIA_PATH，测试后自动清理。"""
    original = settings.MEDIA_PATH
    settings.MEDIA_PATH = str(tmp_path)
    yield
    settings.MEDIA_PATH = original


@pytest.mark.asyncio
async def test_upload_single_file(client: AsyncClient):
    """上传单个文件成功。"""
    file_content = b"hello world"
    response = await client.post(
        "/api/file/upload",
        files=[("files", ("test.txt", file_content, "text/plain"))],
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["total"] == 1
    assert data["files"][0]["original_filename"] == "test.txt"
    assert data["files"][0]["content_type"] == "text/plain"
    assert os.path.exists(data["files"][0]["file_path"])
    print(f"    上传单文件: filename='{data['files'][0]['filename']}', 原始名='test.txt'")


@pytest.mark.asyncio
async def test_upload_multiple_files(client: AsyncClient):
    """上传多个文件成功。"""
    response = await client.post(
        "/api/file/upload",
        files=[
            ("files", ("a.png", b"\x89PNG", "image/png")),
            ("files", ("b.jpg", b"\xff\xd8\xff", "image/jpeg")),
        ],
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["total"] == 2
    assert data["files"][0]["original_filename"] == "a.png"
    assert data["files"][1]["original_filename"] == "b.jpg"
    print(f"    上传多文件: total={data['total']}, files={[f['original_filename'] for f in data['files']]}")


@pytest.mark.asyncio
async def test_upload_long_filename_truncated(client: AsyncClient):
    """文件名超长时被截断到10个字符（保留扩展名）。"""
    long_name = "a" * 50 + ".txt"
    response = await client.post(
        "/api/file/upload",
        files=[("files", (long_name, b"data", "text/plain"))],
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    saved_filename = data["files"][0]["filename"]
    # 文件名中截断部分不应超过10个字符 (去掉时间戳前缀和扩展名)
    name_part = saved_filename.rsplit("_", 1)[-1]  # 取最后一个 _xxx.txt
    name_without_ext = os.path.splitext(name_part)[0]
    assert len(name_without_ext) <= 10
    print(f"    长文件名截断: 原始名='{long_name}' -> 保存为='{saved_filename}'")


@pytest.mark.asyncio
async def test_upload_to_invalid_path_returns_500(client: AsyncClient):
    """MEDIA_PATH 无效时返回 500 错误。"""
    settings.MEDIA_PATH = "/nonexistent/path/that/does/not/exist"
    response = await client.post(
        "/api/file/upload",
        files=[("files", ("fail.txt", b"data", "text/plain"))],
    )
    body = response.json()
    assert body["code"] == 500
    assert "上传失败" in body["message"]
    print(f"    无效路径上传失败: code={body['code']}, message='{body['message']}'")
