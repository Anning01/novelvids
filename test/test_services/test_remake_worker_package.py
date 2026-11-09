import tarfile
from scripts.build_remake_media_worker import WORKER_FILES, build


def test_worker_package_contains_only_media_code_and_locked_dependencies(tmp_path):
    result = build(tmp_path)
    with tarfile.open(tmp_path / result["archive"]) as archive:
        assert set(archive.getnames()) == set(WORKER_FILES)
    requirements = (tmp_path / "requirements.txt").read_text()
    for name in ("scenedetect", "opencv-python-headless", "numpy", "pydantic"):
        assert f"{name}==" in requirements
    for forbidden in ("openai", "asyncpg", "dotenv", "oss"):
        assert forbidden not in requirements
    assert all(".env" not in name and ".anning." not in name for name in WORKER_FILES)
    assert build(tmp_path)["release"] == result["release"]
