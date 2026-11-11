"""Run the real app on an isolated acceptance database, using a local model in memory.

Example: uv run python test/deep_agent_browser.py --source-database PATH --model-config-id 1
The original database is read-only; no credential is copied to the acceptance database.
"""

import argparse
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-database', type=Path, required=True)
    parser.add_argument('--model-config-id', type=int, required=True)
    parser.add_argument('--image-model-config-id', type=int)
    parser.add_argument('--video-model-config-id', type=int)
    parser.add_argument('--database', type=Path, default=Path('data/deep-agent-acceptance.db'))
    parser.add_argument('--checkpoints', type=Path, default=Path('data/deep-agent-acceptance-checkpoints.db'))
    parser.add_argument('--max-output-tokens', type=int)
    parser.add_argument('--ten-chapter-identities', action='store_true')
    parser.add_argument('--port', type=int, default=9010)
    args = parser.parse_args()
    source = args.source_database.resolve(strict=True)
    if len({source, args.database.resolve(), args.checkpoints.resolve()}) != 3:
        raise SystemExit('Source, acceptance and checkpoint databases must use separate paths')
    with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute('SELECT name, base_url, api_key, model, pricing FROM ai_model_configs WHERE id=?',
                                 (args.model_config_id,)).fetchone()
    if row is None:
        raise SystemExit('Model configuration not found')
    media_configs = {}
    with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as connection:
        connection.row_factory = sqlite3.Row
        for kind, identifier in [('image', args.image_model_config_id), ('video', args.video_model_config_id)]:
            if identifier:
                media_configs[kind] = dict(connection.execute('SELECT * FROM ai_model_configs WHERE id=?', (identifier,)).fetchone())
    model = dict(row)
    model['pricing'] = json.loads(model['pricing']) if model['pricing'] else None
    os.environ['DATABASE_URL'] = 'sqlite://' + str(args.database.resolve())
    os.environ['CREATION_AGENT_CHECKPOINT_PATH'] = str(args.checkpoints.resolve())
    os.environ['MODEL_CONFIG_SEED_ENABLED'] = 'false'
    os.environ['MEDIA_LIBRARY_SEED_ENABLED'] = 'false'
    args.database.parent.mkdir(parents=True, exist_ok=True)

    import main as application
    from models.config import AiModelConfig, GeneralConfig
    from models.creation_agent import AgentSettings
    from models.novel import Novel
    from models.chapter import Chapter
    from models.scene import Scene
    from schemas.creation_agent import AgentConfiguration
    from services.creation_agent import handler
    original_model = handler.configured_model

    def authorized_model(config, limits, **kwargs):
        # Use the same provider client and boundary as production; only key storage differs.
        previous = config.api_key
        config.api_key = model['api_key']
        try:
            return original_model(config, limits, **kwargs)
        finally:
            config.api_key = previous

    handler.configured_model = authorized_model
    from controllers.config import ai_model_config_controller
    original_active = ai_model_config_controller.get_active
    memory_keys = {}
    async def active_with_memory_key(*positional, **kwargs):
        config = await original_active(*positional, **kwargs)
        if config.id in memory_keys:
            config.api_key = memory_keys[config.id]
        return config
    ai_model_config_controller.get_active = active_with_memory_key
    original_lifespan = application.app.router.lifespan_context

    @asynccontextmanager
    async def acceptance_lifespan(app):
        async with original_lifespan(app):
            await AiModelConfig.update_or_create(name='DeepSeek · Deep Agents 验收', task_type=7, defaults={
                'base_url': model['base_url'], 'api_key': 'runtime-only', 'model': model['model'],
                'supports_tool_calls': True, 'is_active': True, 'pricing': model['pricing'], 'max_tokens': args.max_output_tokens,
            })
            video_id = None
            for kind, source_config in media_configs.items():
                fields = ('base_url', 'model', 'api_protocol', 'image_model_type', 'video_model_type', 'concurrency')
                data = {key: source_config[key] for key in fields}
                data.update(api_key='runtime-only', is_active=True, pricing=json.loads(source_config['pricing']) if source_config['pricing'] else None)
                item, _ = await AiModelConfig.update_or_create(name=f'{kind} · Assembly 验收', task_type=2 if kind == 'image' else 4, defaults=data)
                memory_keys[item.id] = source_config['api_key']
                if kind == 'video':
                    video_id = item.id
            await AgentSettings.get_or_create(id=1, defaults={'configuration': AgentConfiguration(
                enabled=True, runtime='deepagents', working_input_tokens=16000, max_output_tokens=args.max_output_tokens,
                compaction_trigger_ratio=0.7, compaction_target_ratio=0.25, summary_output_tokens=768,
            ).model_dump()})
            stored = await AgentSettings.get(id=1)
            stored.configuration = AgentConfiguration.model_validate({**stored.configuration, 'max_output_tokens': args.max_output_tokens}).model_dump()
            await stored.save(update_fields=['configuration'])
            await GeneralConfig.get_or_create(id=1, defaults={'prompt_language': 'zh'})
            novel = await Novel.get_or_none(name='Deep Agents 七技能验收')
            if novel is None:
                novel = await Novel.create(name='Deep Agents 七技能验收', total_chapters=2,
                    content='第一章：渡口。林舟在渡口遇见阿宁。\n第二章：灯塔。林舟想起阿宁，听见灯塔信号。')
                first = await Chapter.create(novel=novel, number=1, name='渡口', content='林舟在渡口遇见阿宁。阿宁穿灰色长衣，递给他一张标着灯塔的旧船票。')
                second = await Chapter.create(novel=novel, number=2, name='灯塔', content='林舟想起渡口的阿宁，独自来到灯塔。信号响起，他攥紧那张旧船票，低声说：我听见了。')
                await Scene.create(chapter=first, sequence=1, description='渡口相遇',
                    prompt='渡口，阿宁穿灰色长衣，把旧船票交给林舟。', duration=6)
                await Scene.create(chapter=second, sequence=1, description='灯塔回应',
                    prompt='灯塔外，林舟穿蓝色外套，攥紧旧船票，低声回应信号。', duration=6)
            if args.ten_chapter_identities:
                from test.project_identity_fixture import seed_project_identities
                await seed_project_identities(novel)
            if video_id:
                novel.video_model_config_id = video_id
                await novel.save(update_fields=['video_model_config_id'])
            chapters = await Chapter.filter(novel=novel).order_by('number').values('id', 'number', 'name')
            scenes = await Scene.filter(chapter__novel_id=novel.id).values('id', 'chapter_id')
            print(json.dumps({'acceptance_project': novel.id, 'chapters': chapters, 'scenes': scenes}, ensure_ascii=False), flush=True)
            yield

    application.app.router.lifespan_context = acceptance_lifespan
    import uvicorn
    uvicorn.run(application.app, host='127.0.0.1', port=args.port, log_level='warning')


if __name__ == '__main__':
    main()
