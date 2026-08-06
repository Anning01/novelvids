import csv
import logging
from pathlib import Path
from typing import TypeVar

from tortoise.models import Model

from models.audio_reference import AudioReference
from models.digital_human import DigitalHuman

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SEED_ROOT = PROJECT_ROOT / "seeds"
ModelT = TypeVar("ModelT", bound=Model)


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(f"媒体库初始化文件不存在: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        return [
            {key: value.strip() for key, value in row.items() if key is not None}
            for row in csv.DictReader(source)
        ]


async def _seed_empty_table(model: type[ModelT], rows: list[dict], label: str) -> int:
    existing = await model.all().count()
    if existing:
        logger.info("媒体库启动扫描: %s 已有 %s 条，跳过初始化", label, existing)
        return 0
    if not rows:
        logger.warning("媒体库启动扫描: %s CSV 为空，未创建数据", label)
        return 0
    # 多 worker 同时冷启动时允许另一个进程先写入，唯一资产 ID 保证不会重复。
    await model.bulk_create([model(**row) for row in rows], ignore_conflicts=True)
    logger.info("媒体库启动扫描: %s 为空，已创建 %s 条", label, len(rows))
    return len(rows)


async def ensure_media_library_seed_data(seed_root: Path = SEED_ROOT) -> dict[str, int]:
    """启动时幂等初始化媒体库；表有数据时整表跳过。"""

    audio_rows = _read_csv(seed_root / "audio_references.csv")
    human_rows = _read_csv(seed_root / "digital_humans.csv")
    normalized_humans = [
        {
            "country": row["country"],
            "age": int(row["age"]),
            "gender": row["gender"],
            "occupation": row["occupation"],
            "asset_id": row["asset_id"],
            "image_url": row["image_url"],
        }
        for row in human_rows
    ]
    return {
        "audio_references": await _seed_empty_table(AudioReference, audio_rows, "参考音频"),
        "digital_humans": await _seed_empty_table(DigitalHuman, normalized_humans, "数字人"),
    }
