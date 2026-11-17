"""Bundle the maintained creative Skill directories, including their relative dependencies."""

import posixpath
import re
from urllib.parse import urlsplit
import yaml

from prompts.skill_pack import FILES, ROOT, read_skill
from utils.skill_package import LINK, SkillPackage, package_file

PACKAGES = {'screenplay': 'novelvids-screenplay', 'assets': 'novelvids-assets', 'storyboard': 'novelvids-storyboard'}


def legacy_package(task: str, instructions: str, references: list[dict], description='') -> SkillPackage:
    files, links = [], []
    for index, reference in enumerate(references, 1):
        stem = re.sub(r'[^\w.-]+', '-', reference['name']).strip('.-') or 'reference'
        path = f'references/{index:02d}-{stem}.md'
        files.append(package_file(path, reference['content'].encode('utf-8')))
        links.append(f'- [{reference["name"]}]({path})')
    header = yaml.safe_dump({'name': f'custom-{task}', 'description': description or f'Custom {task} skill'}, allow_unicode=True, sort_keys=False)
    entry = f'---\n{header}---\n\n{instructions}' + ('\n\n' + '\n'.join(links) if links else '')
    return SkillPackage([package_file('SKILL.md', entry.encode('utf-8')), *files])


def builtin_package(task: str) -> SkillPackage:
    if task not in PACKAGES:
        return legacy_package(task, read_skill(task), [], '故事分析与创作素材梳理')
    folder = ROOT / PACKAGES[task]
    resources = {str(ROOT / value): key for key, value in FILES.items()}
    pending = sorted(path for path in folder.rglob('*') if path.is_file() and not path.is_symlink())
    files, seen = [], set()
    original_entry = folder / 'SKILL.md'

    def virtual(path):
        if path == original_entry and task != 'screenplay':
            return 'references/source-skill.md'
        return str(path.relative_to(folder)) if path.is_relative_to(folder) else 'shared/' + str(path.relative_to(ROOT))

    while pending:
        path = pending.pop(0).resolve()
        if path in seen:
            continue
        seen.add(path)
        data = read_skill(resources[str(path)]).encode('utf-8') if str(path) in resources else path.read_bytes()
        file = package_file(virtual(path), data, executable=bool(path.stat().st_mode & 0o111))
        if file['encoding'] == 'utf-8' and path.suffix.lower() == '.md':
            def rewrite(match):
                raw = (match[2] or match[3]).strip('<>')
                url = urlsplit(raw)
                if url.scheme or url.netloc or not url.path:
                    return match[0]
                target = (path.parent / url.path).resolve()
                if not target.is_relative_to(ROOT.resolve()) or not target.is_file() or target.is_symlink():
                    return match[0]
                pending.append(target)
                relative = posixpath.relpath(virtual(target), posixpath.dirname(virtual(path)) or '.')
                if url.fragment:
                    relative += '#' + url.fragment
                return match[1] + relative + match[4]
            file['content'] = LINK.sub(rewrite, file['content'])
        files.append(file)
    if task == 'screenplay':
        return SkillPackage(files)
    from utils.skill_package import entry_metadata
    metadata, _ = entry_metadata(next(file['content'] for file in files if file['path'] == 'references/source-skill.md'))
    # The application entry preserves its single-task method; generic Codex guidance stays available as files.
    method_path = 'references/runtime-method.md'
    files.append(package_file(method_path, read_skill(f'strict_{task}').encode('utf-8')))
    header = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False)
    entry = f'---\n{header}---\n\n完成当前创作任务，遵循 [创作方法]({method_path})。\n'
    files.append(package_file('SKILL.md', entry.encode('utf-8')))
    return SkillPackage(files)
