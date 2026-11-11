"""One bounded media boundary; configured workers never fall back to API-host compute."""
import asyncio
import json
from pathlib import Path
import re
import subprocess
import tarfile
from tempfile import TemporaryDirectory
import threading
from concurrent.futures import ThreadPoolExecutor
from functools import partial

from config import settings
from schemas.media_processing import MediaProcessSpec

_slots = threading.BoundedSemaphore(settings.MEDIA_PROCESSING_CONCURRENCY)
_file_io = ThreadPoolExecutor(max_workers=1, thread_name_prefix='media-files')


async def media_file_io(function, *args, **kwargs):
    # Waiting synchronous callers must not starve the active job's file transfers.
    return await asyncio.get_running_loop().run_in_executor(_file_io, partial(function, *args, **kwargs))


def bounded_command(command):
    command = [str(value) for value in command]
    if command[0] not in {'ffmpeg', 'ffprobe'}:
        raise ValueError('Only media tools are allowed')
    if command[0] == 'ffmpeg':
        args = ['ffmpeg', '-filter_threads', '1', '-filter_complex_threads', '1']
        for value in command[1:-1]:
            if value == '-i':
                args.extend(['-threads', '1'])
            args.append(value)
        command = [*args, '-threads', '1', command[-1]]
    return command


class CommandBundle:
    def __init__(self, command, *, cwd=None, timeout=1200, extra_files=()):
        self.temporary = TemporaryDirectory(prefix='media-job-')
        self.directory = Path(self.temporary.name)
        self.cwd = Path(cwd or Path.cwd()).resolve()
        self.inputs, self.aliases, self.outputs = {}, {}, {}
        command = [str(value) for value in command]
        for value in extra_files:
            self.add(Path(value))
        for value in command[1:]:
            path = Path(value)
            if not path.is_absolute():
                path = self.cwd / path
            try:
                if path.is_file():
                    self.add(path, value)
            except OSError:
                pass  # Filter expressions are not filesystem paths.
        if command[0] == 'ffmpeg':
            output = Path(command[-1])
            if not output.is_absolute():
                output = self.cwd / output
            name = 'output-0' + (output.suffix or '.bin')
            self.outputs[name] = output
            self.aliases[str(output)] = name
            self.aliases[command[-1]] = name
        args = command[1:]
        for source, target in sorted(self.aliases.items(), key=lambda item: -len(item[0])):
            args = [value.replace(source, target) for value in args]
        self.spec = MediaProcessSpec(program=command[0], arguments=args, outputs=list(self.outputs), timeout=int(timeout))
        self.archive = self.directory / 'input.tar'
        self.pack()

    def add(self, source: Path, alias=None):
        path = source.resolve()
        if path in self.inputs:
            if alias:
                self.aliases[alias] = self.inputs[path][0]
            return
        name = f'asset-{len(self.inputs)}' + (path.suffix if path.is_file() else '')
        self.inputs[path] = (name, None)
        self.aliases[str(source)] = name
        self.aliases[str(path)] = name
        if alias:
            self.aliases[alias] = name
        if path.is_dir():
            for child in path.rglob('*'):
                if child.is_file():
                    self.inputs[child] = (f'{name}/{child.relative_to(path).as_posix()}', None)
        elif path.suffix == '.txt':
            text = path.read_text()
            def replace(match):
                child = path.parent / match[1]
                self.add(child)
                return "file '" + self.inputs[child.resolve()][0] + "'"
            self.inputs[path] = (name, re.sub(r"file\s+'([^']+)'", replace, text))

    def pack(self):
        request = self.directory / 'request.json'
        request.write_text(self.spec.model_dump_json())
        with tarfile.open(self.archive, 'w', dereference=True) as tar:
            tar.add(request, arcname='request.json')
            for path, (name, text) in self.inputs.items():
                if path.is_dir():
                    continue
                if text is not None:
                    rewritten = self.directory / name
                    rewritten.write_text(text)
                    path = rewritten
                tar.add(path, arcname=name, recursive=False)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.temporary.cleanup()


async def _remote(bundle):
    from services.remake.remote_media import media_session, SSH_OPTIONS
    from services.media_worker import unpack
    async with media_session() as session:
        await session._run('scp', '-q', *SSH_OPTIONS, str(bundle.archive),
                           f'{session.connection.host}:{session.work}/input.tar')
        await session._command('process')
        output = bundle.directory / 'output.tar'
        await session._run('scp', '-q', *SSH_OPTIONS,
                           f'{session.connection.host}:{session.work}/output.tar', str(output))
        directory = bundle.directory / 'result'
        await media_file_io(unpack, output, directory)
        result = json.loads((directory / 'result.json').read_text())
        if result['returncode'] == 0:
            import os
            import shutil
            from tempfile import NamedTemporaryFile
            for name, destination in bundle.outputs.items():
                destination.parent.mkdir(parents=True, exist_ok=True)
                with NamedTemporaryFile(dir=destination.parent, prefix='.media-', delete=False) as staged:
                    temporary = Path(staged.name)
                try:
                    await media_file_io(shutil.copyfile, directory / name, temporary)
                    os.replace(temporary, destination)
                finally:
                    temporary.unlink(missing_ok=True)
        return result


def _result(command, result, options):
    stdout, stderr = result['stdout'], result['stderr']
    if not (options.get('text') or options.get('encoding')):
        stdout, stderr = stdout.encode(), stderr.encode()
    completed = subprocess.CompletedProcess(command, result['returncode'], stdout, stderr)
    if options.get('check'):
        completed.check_returncode()
    return completed


def run_media(command, *, extra_files=(), **options):
    from config import settings
    with _slots:
        if not settings.REMAKE_MEDIA_SSH_HOST:
            return subprocess.run(bounded_command(command), **options)
        with CommandBundle(bounded_command(command), cwd=options.get('cwd'),
                           timeout=options.get('timeout', 1200), extra_files=extra_files) as bundle:
            return _result(command, asyncio.run(_remote(bundle)), options)


async def run_media_async(command, *, extra_files=(), **options):
    from config import settings
    while not _slots.acquire(blocking=False):
        await asyncio.sleep(.05)
    try:
        if settings.REMAKE_MEDIA_SSH_HOST:
            bundle = await media_file_io(CommandBundle, bounded_command(command), cwd=options.get('cwd'),
                                             timeout=options.get('timeout', 1200), extra_files=extra_files)
            with bundle:
                return _result(command, await _remote(bundle), options)
        process = await asyncio.create_subprocess_exec(*bounded_command(command), cwd=options.get('cwd'),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), options.get('timeout', 1200))
        finally:
            if process.returncode is None:
                process.kill()
                await process.communicate()
        return _result(command, {'returncode': process.returncode,
                                'stdout': stdout.decode(errors='replace'), 'stderr': stderr.decode(errors='replace')}, options)
    finally:
        _slots.release()


def image_derivatives(image_bytes):
    from config import settings
    from services.media_images import render_derivatives
    with _slots:
        if not settings.REMAKE_MEDIA_SSH_HOST:
            return render_derivatives(image_bytes)
        with TemporaryDirectory(prefix='image-input-') as directory:
            source = Path(directory) / 'image.bin'
            source.write_bytes(image_bytes)
            with CommandBundle(['ffprobe', str(source)]) as bundle:
                bundle.spec = MediaProcessSpec(program='derivatives', arguments=bundle.spec.arguments,
                    outputs=['output-0.webp', 'output-1.webp'])
                bundle.outputs = {name: Path(directory) / name for name in bundle.spec.outputs}
                bundle.pack()
                result = asyncio.run(_remote(bundle))
                if result['returncode']:
                    raise ValueError('Image processing failed')
                return {kind: bundle.outputs[name].read_bytes()
                        for kind, name in zip(('thumbnail', 'preview'), bundle.spec.outputs, strict=True)}
