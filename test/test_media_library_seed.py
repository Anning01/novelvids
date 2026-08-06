import csv

from models.audio_reference import AudioReference
from models.digital_human import DigitalHuman
from services.media_library_seed import ensure_media_library_seed_data


def _write_csv(path, fieldnames, rows):
    with path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


async def test_seed_creates_missing_media_libraries_and_then_skips(tmp_path):
    _write_csv(
        tmp_path / "audio_references.csv",
        ["nickname", "gender", "audio_url", "avatar_url", "asset_id"],
        [{
            "nickname": "旁白",
            "gender": "女",
            "audio_url": "https://example.com/voice.mp3",
            "avatar_url": "https://example.com/voice.png",
            "asset_id": "audio-1",
        }],
    )
    _write_csv(
        tmp_path / "digital_humans.csv",
        ["country", "age", "gender", "occupation", "asset_id", "image_url"],
        [{
            "country": "中国",
            "age": "24",
            "gender": "女",
            "occupation": "演员",
            "asset_id": "digital-1",
            "image_url": "https://example.com/digital.png",
        }],
    )

    assert await ensure_media_library_seed_data(tmp_path) == {
        "audio_references": 1,
        "digital_humans": 1,
    }
    assert await AudioReference.all().count() == 1
    assert await DigitalHuman.all().count() == 1

    assert await ensure_media_library_seed_data(tmp_path) == {
        "audio_references": 0,
        "digital_humans": 0,
    }
    assert await AudioReference.all().count() == 1
    assert await DigitalHuman.all().count() == 1


async def test_media_library_api_only_returns_active_resources(client):
    await AudioReference.create(
        nickname="旁白",
        gender="女",
        audio_url="https://example.com/voice.mp3",
        avatar_url="https://example.com/voice.png",
        asset_id="audio-active",
    )
    await AudioReference.create(
        nickname="停用",
        gender="男",
        audio_url="https://example.com/off.mp3",
        avatar_url="https://example.com/off.png",
        asset_id="audio-off",
        is_active=False,
    )
    await DigitalHuman.create(
        country="中国",
        age=24,
        gender="女",
        occupation="演员",
        asset_id="digital-active",
        image_url="https://example.com/digital.png",
    )

    audio_response = await client.get("/api/media-library/audio-references?page_size=100")
    human_response = await client.get("/api/media-library/digital-humans?page_size=100")

    assert audio_response.status_code == 200
    assert [item["asset_id"] for item in audio_response.json()["data"]["items"]] == ["audio-active"]
    assert human_response.status_code == 200
    assert [item["asset_id"] for item in human_response.json()["data"]["items"]] == ["digital-active"]


async def test_media_library_api_supports_gender_synonym_filter(client):
    for index, gender in enumerate(["女", "女性", "男", "男性"], start=1):
        await DigitalHuman.create(
            country="中国",
            age=20 + index,
            gender=gender,
            occupation="演员",
            asset_id=f"digital-{index}",
            image_url=f"https://example.com/digital-{index}.png",
        )

    response = await client.get(
        "/api/media-library/digital-humans",
        params={"page_size": 100, "gender__in": "女,女性"},
    )

    assert response.status_code == 200
    assert {item["gender"] for item in response.json()["data"]["items"]} == {"女", "女性"}
