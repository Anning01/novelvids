"""Read bounded files under a user-selected root; archive bytes before persistence."""
import hashlib
import json
from pathlib import Path
from schemas.work_package import Assets, Episode, Shot, Storyboard

MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_PACKAGE_BYTES = 1024 * 1024 * 1024


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


class PackageFiles:
    def __init__(self, directory: str, allowed_root: Path):
        self.root = Path(directory).resolve(strict=True)
        if not self.root.is_dir() or not self.root.is_relative_to(allowed_root.resolve()):
            raise ValueError('作品目录必须位于启动时授权的目录内')
        self.files: dict[str, bytes] = {}

    def read(self, relative: str) -> bytes:
        path = Path(relative)
        if (path.is_absolute() or '..' in path.parts or not path.parts
                or any(part.startswith('.') for part in path.parts)
                or path.suffix.lower() not in {'.md', '.txt', '.json', '.pdf', '.docx', '.csv',
                    '.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg', '.mp4', '.mov', '.webm',
                    '.mp3', '.wav', '.m4a', '.ogg', '.flac'}):
            raise ValueError('只接受作品目录内的相对文件路径')
        source = (self.root / path).resolve(strict=True)
        if not source.is_relative_to(self.root) or not source.is_file():
            raise ValueError('素材路径越界或不是普通文件')
        if source.stat().st_size > MAX_FILE_BYTES:
            raise ValueError('单文件超过 256 MiB')
        if relative not in self.files:
            data = source.read_bytes()
            if len(data) > MAX_FILE_BYTES or sum(map(len, self.files.values())) + len(data) > MAX_PACKAGE_BYTES:
                raise ValueError('作品包超过大小限制')
            self.files[relative] = data
        return self.files[relative]

    def json(self, relative: str):
        return json.loads(self.read(relative))

    def media(self, shot: Shot):
        for media in shot.media:
            if media.role in {"storyboard", "blocking"}:
                extensions = {".png", ".jpg", ".jpeg", ".webp"}
                if media.role == "blocking":
                    extensions.add(".svg")
                if Path(media.path).suffix.lower() not in extensions:
                    raise ValueError("分镜制作图需使用支持的图片格式")
            self.read(media.path)

    def episode(self):
        manifest = Episode.model_validate(self.json('episode.json'))
        screenplay = self.read(manifest.screenplay).decode('utf-8')
        if manifest.source_text is not None:
            self.read(manifest.source_text).decode("utf-8-sig")
        assets = Assets.model_validate(self.json(manifest.assets)).assets
        board = Storyboard.model_validate(self.json(manifest.storyboard))
        for filename in manifest.originals:
            self.read(filename)
        for asset in assets:
            for obj in [asset, *asset.variants]:
                for media in obj.media:
                    self.read(media.path)
        for shot in board.shots:
            self.media(shot)
        ids = [a.id for a in assets]
        scenes = [s.id for s in board.scenes]
        shots = [s.id for s in board.shots]
        variants = [v.id for a in assets for v in a.variants]
        for values in (ids, scenes, shots, variants):
            if len(values) != len(set(values)):
                raise ValueError('稳定 ID 重复')
        catalog = {a.id: a for a in assets}
        for shot in board.shots:
            if shot.scene_id not in scenes:
                raise ValueError('镜头引用了未登记的场')
            for ref in shot.visual:
                if ref.asset_id not in catalog or (ref.variant_id and ref.variant_id not in {v.id for v in catalog[ref.asset_id].variants}):
                    raise ValueError('画面资产或形态引用无效')
            if any(v.asset_id not in catalog for v in shot.voices):
                raise ValueError('声音资产引用无效')
        return manifest, screenplay, assets, board

    def archive(self, destination: Path) -> dict[str, str]:
        urls = {}
        for relative, data in self.files.items():
            # Content addressing avoids overwriting old imported revisions.
            key = hashlib.sha256(data).hexdigest() + Path(relative).suffix.lower()
            target = destination / key
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.write_bytes(data)
            urls[relative] = '/media/work-packages/' + key
        return urls

    def receipt(self, receipt: dict):
        target = self.root / 'sync-receipt.json'
        if target.is_symlink():
            raise ValueError('回执文件不能是符号链接')
        temporary = self.root / '.sync-receipt.tmp'
        if temporary.is_symlink():
            raise ValueError('回执临时文件不能是符号链接')
        temporary.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(target)
