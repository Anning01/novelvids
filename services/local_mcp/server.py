"""Run with python -m services.local_mcp.server --allow-root PATH (stdio only)."""
import argparse
import asyncio
import json
import logging
from pathlib import Path
import sys
from pydantic import ValidationError
from tortoise import Tortoise
from config import settings
from schemas.work_package import ImportEpisode, ReadEpisode, UpdateShot
from services.local_mcp.sync import SyncConflict, WorkSync

TOOLS = {
    'import_episode': (ImportEpisode, '导入用户已确认的一集作品包；首次导入或相同请求重试，不覆盖已有集。'),
    'read_episode': (ReadEpisode, '读取作品/集定位与镜头当前版本、内容；同步前用于比较本地修改。'),
    'update_shot': (UpdateShot, '用户明确要求同步时，按稳定 ID 和 base_version 更新一个镜头；冲突停止，不影响顺序或旧视频。'),
}
VERSIONS = {'2024-11-05', '2025-03-26', '2025-06-18', '2025-11-25'}


class MCPServer:
    def __init__(self, sync):
        self.sync = sync
        self.initialized = False

    async def handle(self, message):
        if not isinstance(message, dict) or message.get('jsonrpc') != '2.0' or not isinstance(message.get('method'), str):
            return {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32600, 'message': 'Invalid Request'}}
        if 'id' not in message:
            return None
        response = {'jsonrpc': '2.0', 'id': message['id']}
        method, params = message['method'], message.get('params', {})
        if not isinstance(params, dict):
            return {**response, 'error': {'code': -32602, 'message': 'Invalid params'}}
        if method == 'initialize':
            self.initialized = True
            version = params.get('protocolVersion')
            result = {'protocolVersion': version if isinstance(version, str) and version in VERSIONS else '2025-03-26',
                      'capabilities': {'tools': {'listChanged': False}},
                      'serverInfo': {'name': 'novelvids-local', 'version': '1.0.0'}}
        elif method == 'ping':
            result = {}
        elif not self.initialized:
            return {**response, 'error': {'code': -32000, 'message': 'Initialize first'}}
        elif method == 'tools/list':
            result = {'tools': [{'name': name, 'description': description, 'inputSchema': model.model_json_schema(),
                                'annotations': {'readOnlyHint': name == 'read_episode', 'destructiveHint': False}}
                               for name, (model, description) in TOOLS.items()]}
        elif method == 'tools/call':
            name = params.get('name')
            if not isinstance(name, str) or name not in TOOLS:
                return {**response, 'error': {'code': -32602, 'message': 'Unknown tool'}}
            try:
                request = TOOLS[name][0].model_validate(params.get('arguments', {}))
                value = await getattr(self.sync, name)(request)
                result = {'content': [{'type': 'text', 'text': json.dumps(value, ensure_ascii=False)}], 'isError': False}
            except SyncConflict as exc:
                result = {'content': [{'type': 'text', 'text': json.dumps(exc.details, ensure_ascii=False)}], 'isError': True}
            except ValidationError as exc:
                value = {'status': 'invalid_input', 'fields': [list(e['loc']) for e in exc.errors()]}
                result = {'content': [{'type': 'text', 'text': json.dumps(value)}], 'isError': True}
            except (ValueError, OSError) as exc:
                # Do not echo paths, source text, credentials or database queries.
                value = {'status': 'rejected', 'error_type': type(exc).__name__}
                if isinstance(exc, ValueError):
                    value['message'] = str(exc)
                result = {'content': [{'type': 'text', 'text': json.dumps(value, ensure_ascii=False)}], 'isError': True}
            except Exception:
                result = {'content': [{'type': 'text', 'text': '{"status":"failed","message":"同步失败；数据库事务已回滚，请检查本地服务"}'}], 'isError': True}
        else:
            return {**response, 'error': {'code': -32601, 'message': 'Method not found'}}
        return {**response, 'result': result}


async def run(args):
    if settings.AUTH_ENABLED:
        raise ValueError('本地 MCP 仅支持 AUTH_ENABLED=false 的独立本地实例，不可连接启用登录的生产库')
    import models
    await Tortoise.init(db_url=settings.DATABASE_URL,
                        modules={'models': [f'models.{name}' for name in models.__all__]}, timezone='Asia/Shanghai')
    try:
        # Only additive missing tables; no seeds, migrations, analysis or background jobs.
        from services.schema_compat import ensure_chapter_screenplay_schema
        await ensure_chapter_screenplay_schema()
        await Tortoise.generate_schemas(safe=True)
        server = MCPServer(WorkSync(args.allow_root.resolve(strict=True), Path(settings.MEDIA_PATH).resolve(), args.app_url))
        while line := await asyncio.to_thread(sys.stdin.buffer.readline):
            try:
                message = json.loads(line)
            except (ValueError, UnicodeError):
                response = {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': 'Parse error'}}
            else:
                response = await server.handle(message)
            if response is not None:
                print(json.dumps(response, ensure_ascii=False), flush=True)
    finally:
        await Tortoise.close_connections()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-root', type=Path, required=True, help='Only read/write package directories beneath this root')
    parser.add_argument('--app-url', default='http://localhost:3000', help='Browser URL of the local NovelVids frontend')
    args = parser.parse_args()
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    try:
        asyncio.run(run(args))
    except Exception as exc:
        print(f'MCP startup failed: {type(exc).__name__}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
