"""Bounded, portable Skill folders. Archives are read in memory, never extracted or executed."""

import base64
import binascii
import hashlib
import io
import posixpath
import re
import stat
import unicodedata
from urllib.parse import unquote, urlsplit
import zipfile

import yaml

MAX_FILES = 200
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_PACKAGE_BYTES = 20 * 1024 * 1024
MAX_ARCHIVE_BYTES = 20 * 1024 * 1024
PACKAGE_LIMITS = {'max_files': MAX_FILES, 'max_file_bytes': MAX_FILE_BYTES,
    'max_package_bytes': MAX_PACKAGE_BYTES, 'max_archive_bytes': MAX_ARCHIVE_BYTES}
LINK = re.compile(r'(!?\[[^\]\n]*\]\()(?:(<[^>]+>)|([^\s)]+))([^)]*\))')
RESOURCE_PATH = re.compile(r'(?<![\w/:.])(?:[\w.-]+/)+[\w.-]+')


def validate_file_path(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 240 or any(ord(char) < 32 or ord(char) == 127 or char in '\\:' for char in value):
        raise ValueError('文件路径无效，请使用技能目录内的相对路径')
    if any(part in ('', '.', '..') for part in value.split('/')):
        raise ValueError('文件路径无效，请使用技能目录内的相对路径')
    return value


def file_bytes(file: dict) -> bytes:
    if file.get('encoding', 'utf-8') == 'utf-8':
        return file['content'].encode('utf-8')
    try:
        return base64.b64decode(file['content'], validate=True)
    except (binascii.Error, ValueError):
        raise ValueError('文件内容编码无效') from None


def package_file(path: str, data: bytes, *, executable=False) -> dict:
    try:
        content = data.decode('utf-8')
        if '\0' in content:
            raise UnicodeDecodeError('utf-8', data, 0, 1, 'binary')
        encoding = 'utf-8'
    except UnicodeDecodeError:
        content, encoding = base64.b64encode(data).decode('ascii'), 'base64'
    return {'path': path, 'content': content, 'encoding': encoding, 'executable': executable}


def entry_metadata(content: str) -> tuple[dict, str]:
    lines = content.splitlines(keepends=True)
    if not lines or lines[0].strip().lstrip('\ufeff') != '---':
        raise ValueError('SKILL.md 需要 YAML 头信息，包含 name 和 description')
    end = next((index for index, line in enumerate(lines[1:], 1) if line.strip() == '---'), None)
    if end is None or sum(len(line) for line in lines[:end]) > 16384:
        raise ValueError('SKILL.md 的 YAML 头信息无效')
    try:
        metadata = yaml.safe_load(''.join(lines[1:end]))
    except (yaml.YAMLError, RecursionError):
        raise ValueError('SKILL.md 的 YAML 头信息无效') from None
    if not isinstance(metadata, dict):
        raise ValueError('SKILL.md 需要 YAML 头信息，包含 name 和 description')
    name, description = metadata.get('name'), metadata.get('description')
    if not isinstance(name, str) or len(name) > 64 or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', name):
        raise ValueError('SKILL.md 的 name 只能使用小写字母、数字和单连字符，最多 64 个字符')
    if not isinstance(description, str) or not description.strip() or len(description) > 1024:
        raise ValueError('SKILL.md 的 description 必须为 1–1024 个字符')
    return metadata, ''.join(lines[end + 1:])


def relative_target(source: str, target: str) -> str | None:
    url = urlsplit(target.strip('<>'))
    if url.scheme or url.netloc or not url.path:
        return None
    target = posixpath.normpath(posixpath.join(posixpath.dirname(source), unquote(url.path)))
    return validate_file_path(target)


class SkillPackage:
    def __init__(self, files: list[dict]):
        if not files or len(files) > MAX_FILES:
            raise ValueError('技能包需要 1–200 个文件')
        self.files = []
        seen = set()
        total = 0
        for raw in files:
            path = validate_file_path(raw['path'])
            identity = unicodedata.normalize('NFC', path).casefold()
            if identity in seen:
                raise ValueError('技能包包含重复或大小写冲突的文件路径')
            seen.add(identity)
            data = file_bytes(raw)
            total += len(data)
            if len(data) > MAX_FILE_BYTES or total > MAX_PACKAGE_BYTES:
                raise ValueError('单个文件最多 5 MB，技能包解压后最多 20 MB')
            self.files.append({**raw, 'path': path, 'encoding': raw.get('encoding', 'utf-8'),
                'executable': bool(raw.get('executable', False))})
        self.files.sort(key=lambda file: (file['path'] != 'SKILL.md', file['path']))
        self.by_path = {file['path']: file for file in self.files}
        nodes = {}
        for path in self.by_path:
            parts = path.split('/')
            for index in range(1, len(parts) + 1):
                node = '/'.join(parts[:index])
                key = unicodedata.normalize('NFC', node).casefold()
                if key in nodes and nodes[key] != node:
                    raise ValueError('技能包包含重复或大小写冲突的文件路径')
                if index < len(parts) and node in self.by_path:
                    raise ValueError('文件与文件夹路径冲突')
                nodes[key] = node
        entry = self.by_path.get('SKILL.md')
        if entry is None or entry['encoding'] != 'utf-8':
            raise ValueError('技能根目录必须包含 UTF-8 格式的 SKILL.md')
        if len(entry['content'].encode('utf-8')) > 128 * 1024:
            raise ValueError('SKILL.md 最多 128 KB，请将详细内容拆分到其他文件')
        self.metadata, self.body = entry_metadata(entry['content'])

    @classmethod
    def from_archive(cls, data: bytes):
        if len(data) > MAX_ARCHIVE_BYTES:
            raise ValueError('压缩包最多 20 MB')
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                entries = archive.infolist()
                if len(entries) > MAX_FILES * 2:
                    raise ValueError('压缩包文件数量过多')
                files = []
                total = 0
                for entry in entries:
                    if '\0' in entry.orig_filename:
                        raise ValueError('文件路径无效，请使用技能目录内的相对路径')
                    path = entry.filename.rstrip('/')
                    validate_file_path(path)
                    if '__MACOSX' in path.split('/') or path.split('/')[-1] == '.DS_Store':
                        continue
                    mode = entry.external_attr >> 16
                    if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)):
                        raise ValueError('技能包不支持符号链接或特殊文件')
                    if entry.is_dir():
                        continue
                    total += entry.file_size
                    if entry.file_size > MAX_FILE_BYTES or total > MAX_PACKAGE_BYTES or len(files) >= MAX_FILES:
                        raise ValueError('单个文件最多 5 MB，技能包解压后最多 20 MB')
                    if entry.flag_bits & 1:
                        raise ValueError('请上传未加密的 ZIP 或 .skill 压缩包')
                    if entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                        raise ValueError('请使用标准 ZIP 压缩方式，不支持其他压缩算法')
                    with archive.open(entry) as stream:
                        content = stream.read(MAX_FILE_BYTES + 1)
                    files.append(package_file(path, content, executable=bool(mode & 0o111)))
        except (zipfile.BadZipFile, NotImplementedError, RuntimeError, OSError, EOFError):
            raise ValueError('请上传有效且未加密的 ZIP 或 .skill 压缩包') from None
        # Accept a Skill directly or inside one archive wrapper folder.
        roots = [file['path'][:-len('SKILL.md')] for file in files if file['path'].split('/')[-1] == 'SKILL.md']
        if not roots:
            raise ValueError('压缩包中未找到 SKILL.md')
        depth = min(root.count('/') for root in roots)
        candidates = [root for root in roots if root.count('/') == depth]
        if len(candidates) != 1 or any(not file['path'].startswith(candidates[0]) for file in files):
            raise ValueError('每个压缩包只能包含一个完整的 Skill 文件夹')
        prefix = candidates[0]
        return cls([{**file, 'path': file['path'][len(prefix):]} for file in files])

    def linked_paths(self) -> list[str]:
        pending, visited, resources = ['SKILL.md'], set(), []
        queued = {'SKILL.md'}
        def add(path):
            if path not in queued:
                queued.add(path)
                pending.append(path)
        while pending:
            path = pending.pop(0)
            if path in visited:
                continue
            visited.add(path)
            file = self.by_path[path]
            if path != 'SKILL.md':
                resources.append(path)
            if file['encoding'] != 'utf-8' or not path.lower().endswith('.md'):
                continue
            text = file['content']
            prose = re.sub(r'(?ms)^\s*```[^\n]*\n.*?^\s*```[^\n]*$', '', text)
            for match in LINK.finditer(prose):
                target = relative_target(path, match[2] or match[3])
                if target is None:
                    continue
                if target in self.by_path:
                    add(target)
                else:
                    children = [name for name in self.by_path if name.startswith(target.rstrip('/') + '/')]
                    if not children:
                        raise ValueError(f'文件引用不存在：{path} → {target}')
                    for child in children:
                        add(child)
            # Skill commands often mention resource paths in backticks, without Markdown links.
            for match in RESOURCE_PATH.finditer(text):
                mentioned = match[0]
                if any(part.startswith('.') for part in mentioned.split('/')):
                    continue
                try:
                    target = relative_target(path, mentioned)
                except ValueError:
                    continue
                if target not in self.by_path and mentioned in self.by_path:
                    target = mentioned
                if target in self.by_path:
                    add(target)
        return resources

    def as_method(self) -> dict:
        resources = self.linked_paths()
        manifest = []
        for path in ['SKILL.md', *resources]:
            file = self.by_path[path]
            data = file_bytes(file)
            manifest.append({'path': path, 'encoding': file['encoding'], 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
        return {'instructions': self.by_path['SKILL.md']['content'], 'references': [
            {'name': path, 'content': self.by_path[path]['content'], 'render_placeholders': path.lower().endswith('.md')}
            for path in resources if self.by_path[path]['encoding'] == 'utf-8'], 'file_manifest': manifest}

    def archive(self) -> bytes:
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
            for file in self.files:
                info = zipfile.ZipInfo(f'{self.metadata["name"]}/{file["path"]}')
                info.external_attr = (0o100755 if file['executable'] else 0o100644) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, file_bytes(file))
        return output.getvalue()

