"""Run staged media jobs without application, database or storage credentials."""
import json
from pathlib import Path
import subprocess
import tarfile

from schemas.media_processing import MediaProcessSpec


def unpack(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as tar:
        members = tar.getmembers()
        if len(members) > 10000 or sum(m.size for m in members) > 8 * 1024**3:
            raise ValueError('Media archive exceeds limits')
        for member in members:
            path = destination / member.name
            if not member.isfile() or not path.resolve().is_relative_to(destination.resolve()):
                raise ValueError('Media archive contains an unsafe entry')
        tar.extractall(destination, members=members, filter='data')


def execute(work: Path) -> dict:
    unpack(work / 'input.tar', work / 'processing')
    directory = work / 'processing'
    spec = MediaProcessSpec.model_validate_json((directory / 'request.json').read_text())
    if spec.program == 'derivatives':
        from services.media_images import render_derivatives
        rendered = render_derivatives((directory / spec.arguments[0]).read_bytes())
        for name, data in zip(spec.outputs, rendered.values(), strict=True):
            (directory / name).write_bytes(data)
        result = {'returncode': 0, 'stdout': '', 'stderr': ''}
    else:
        with (directory / 'stdout').open('wb') as out, (directory / 'stderr').open('wb') as err:
            process = subprocess.run([spec.program, *spec.arguments], cwd=directory,
                stdin=subprocess.DEVNULL, stdout=out, stderr=err, timeout=spec.timeout)
        with (directory / 'stdout').open('rb') as out, (directory / 'stderr').open('rb') as err:
            err.seek(max(0, (directory / 'stderr').stat().st_size - 65536))
            result = {'returncode': process.returncode,
                      'stdout': out.read(1024 * 1024).decode(errors='replace'),
                      'stderr': err.read(65536).decode(errors='replace')}
    (directory / 'result.json').write_text(json.dumps(result))
    with tarfile.open(work / 'output.tar', 'w') as tar:
        tar.add(directory / 'result.json', arcname='result.json')
        for name in spec.outputs:
            path = directory / name
            if path.is_file():
                tar.add(path, arcname=name)
    return {'ok': True}
