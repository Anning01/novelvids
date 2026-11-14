"""Package orchestration using the workbench's canonical objects and write locks."""
import json
from pathlib import Path
from urllib.parse import urlsplit
from tortoise.transactions import in_transaction
from models.novel import Novel
from models.chapter import Chapter
from schemas.chapter import ChapterCreate
from controllers.chapter import chapter_controller
from controllers.novel import novel_controller
from schemas.novel import NovelCreate
from controllers.asset import asset_controller
from models.scene import Scene
from models.work_sync import WorkSyncObject, WorkSyncRequest
from prompts.skill_pack import read_skill
from services.project_config import validate_project_config
from fastapi import HTTPException
from auth.deps import AuthContext, ensure_novel_access
from config import settings
from prompts.reference import CHARACTER_TURNAROUND, GROUP_PORTRAIT
from schemas.work_package import ImportEpisode, ReadEpisode, Shot, UpdateShot
from services.creation_objects import CreationObjects, project_write
from services.creation_agent.object_state import write_fields
from services.extraction.extractor import validate_asset_design
from services.local_mcp.package import PackageFiles, digest


class SyncConflict(ValueError):
    def __init__(self, reason: str, **details):
        self.details = {'status': 'conflict', 'reason': reason, **details}
        super().__init__(reason)


class WorkSync:
    def __init__(self, allowed_root: Path, media_root: Path, app_url: str = "http://localhost:3000"):
        parsed = urlsplit(app_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("猫影网页地址必须是无登录信息、查询或片段的 HTTP(S) 地址")
        self.ctx = None
        self.app_url = app_url.rstrip("/")
        self.allowed_root = allowed_root
        self.archive_root = media_root / 'work-packages'

    def for_context(self, ctx: AuthContext):
        if not ctx.user or not ctx.team_id:
            raise HTTPException(403, "需要已登录的团队成员")
        scoped = WorkSync(self.allowed_root, self.archive_root.parent, self.app_url)
        scoped.ctx = ctx
        return scoped

    def work_key(self, work):
        if settings.AUTH_ENABLED and self.ctx is None:
            raise HTTPException(401, "MCP 尚未连接猫影登录会话")
        return f"t{self.ctx.team_id}:{digest(work)}" if self.ctx else work

    def request_key(self, request_id):
        if settings.AUTH_ENABLED and self.ctx is None:
            raise HTTPException(401, "MCP 尚未连接猫影登录会话")
        if self.ctx:
            return f"t{self.ctx.team_id}:u{self.ctx.user.id}:{digest(request_id)}"
        return request_id

    async def mapping(self, work, episode, kind, stable):
        row = await WorkSyncObject.get_or_none(work_id=self.work_key(work), episode_id=episode, kind=kind, stable_id=stable)
        if row is None:
            raise ValueError(f'未登记的 {kind} 稳定 ID')
        return row

    async def register(self, work, episode, kind, stable, local_id, payload):
        return await WorkSyncObject.create(work_id=self.work_key(work), episode_id=episode, kind=kind,
                                         stable_id=stable, local_id=local_id, payload=payload)

    async def replay(self, request_id, fingerprint):
        previous = await WorkSyncRequest.get_or_none(request_id=self.request_key(request_id))
        if previous:
            if previous.payload_hash != fingerprint:
                raise SyncConflict('request_id_reused', message='此请求 ID 已用于不同内容，请使用新的请求 ID')
            project = await self.project(previous.receipt["work_id"])
            if project.id != previous.receipt["novel_id"]:
                raise HTTPException(403, "此回执不属于当前作品")
            receipt = {**previous.receipt}
            receipt["location"] = self.location(receipt["novel_id"], receipt["chapter_id"], receipt["location"]["episode_number"])
            return receipt
        return None

    def location(self, novel_id, chapter_id, number):
        path = f'/#/create/short-drama/storyboard/{novel_id}?chapter={chapter_id}'
        return {'novel_id': novel_id, 'chapter_id': chapter_id, 'episode_number': number,
                'path': path, 'url': self.app_url + path}

    async def link_episode_assets(self, work, chapter, assets, board, objects):
        for asset in assets:
            mapping = await self.mapping(work, '', 'asset', asset.id)
            target = await asset_controller.reuse_in_chapter(mapping.local_id, chapter.id)
            mapping.payload = {**mapping.payload, 'version': await objects.recovery_version(target)}
            await mapping.save(update_fields=['payload'])
            selected = {ref.variant_id for shot in board.shots for ref in shot.visual
                        if ref.asset_id == asset.id}
            for variant in asset.variants:
                row = await self.mapping(work, '', 'variant', variant.id)
                target = await objects.get('variant', row.local_id)
                if row.payload.get('version') and row.payload['version'] != await objects.recovery_version(target):
                    raise SyncConflict('variant_changed', variant_id=variant.id)
                # Mixed base/forms or several forms use explicit shot bindings, never an episode-wide default.
                if selected == {variant.id}:
                    numbers = sorted(set(target.chapter_numbers or []) | {chapter.number})
                    await write_fields(objects, target, {'chapter_numbers': numbers})
                row.payload = {**row.payload, 'version': await objects.recovery_version(target)}
                await row.save(update_fields=['payload'])

    async def project(self, work_id):
        row = await self.mapping(work_id, '', 'work', work_id)
        project = await Novel.get_or_none(id=row.local_id)
        if project is None:
            raise ValueError('作品不存在或已移除，不能通过导入恢复')
        if self.ctx:
            await ensure_novel_access(project.id, self.ctx)
            if project.team_id != self.ctx.team_id:
                raise HTTPException(404, "作品不属于当前团队")
        elif project.team_id is not None:
            raise ValueError('本地 MCP 不支持团队作品；请使用独立的本地无登录实例')
        return project

    async def scene_values(self, work_id, shot, urls):
        from services.video.asset_resolver import add_variant_binding

        assets, bindings = [], {}
        for ref in shot.visual:
            asset = await self.mapping(work_id, '', 'asset', ref.asset_id)
            if asset.local_id not in assets:
                assets.append(asset.local_id)
            if ref.variant_id:
                variant = await self.mapping(work_id, '', 'variant', ref.variant_id)
                if variant.payload['asset_id'] != ref.asset_id:
                    raise ValueError('形态不属于指定资产')
                add_variant_binding(bindings, asset.local_id, variant.local_id)
            else:
                add_variant_binding(bindings, asset.local_id, None)
        voice_asset_ids = {}
        for key in dict.fromkeys(voice.asset_id for voice in shot.voices):
            asset = await self.mapping(work_id, '', 'asset', key)
            voice_asset_ids[key] = asset.local_id
        if voice_asset_ids:
            await CreationObjects((await self.project(work_id)).id).active_assets(list(voice_asset_ids.values()))
        return {'description': shot.description, 'prompt': shot.prompt, 'duration': shot.duration,
                'prompt_params': shot.structure,
                'metadata': {'asset_variant_ids': bindings, 'voice_asset_ids': voice_asset_ids, 'work_package': shot.model_dump(),
                             'imported_media': [{**m.model_dump(), 'url': urls[m.path]} for m in shot.media]}}, assets, bindings

    async def persist_shot(self, objects, chapter_id, work_id, episode_id, shot, urls, target=None, preserve_visual=False, sync_media=True, language="zh"):
        values, assets, bindings = await self.scene_values(work_id, shot, urls)
        if target is not None and preserve_visual:
            assets = await target.assets.all().values_list('id', flat=True)
            bindings = (target.metadata or {}).get('asset_variant_ids') or {}
            values['metadata']['asset_variant_ids'] = bindings
        await objects.active_assets(assets)
        await objects.validate_variant_bindings(assets, bindings)
        metadata = {**(target.metadata if target else {}), **values['metadata']}
        if sync_media:
            sheet = next((m for m in shot.media if m.role == "storyboard"), None)
            if sheet:
                guidance = json.loads(read_skill("storyboard_sheet_templates"))[language]["video"]
                supplied = shot.structure.get("storyboard_sheet") or {}
                guidance = supplied.get("video_guidance") or guidance
                metadata["storyboard_sheet"] = {"source": "work_package", "status": "completed",
                    "image_url": urls[sheet.path], "video_prompt": supplied.get("video_prompt") or shot.prompt + "\n\n" + guidance,
                    "image_prompt": supplied.get("image_prompt") or "",
                    "video_guidance": guidance}
            elif (metadata.get("storyboard_sheet") or {}).get("source") == "work_package":
                metadata.pop("storyboard_sheet")
        values["metadata"] = metadata
        if target is None:
            target = await objects.create_scene(chapter_id, after_id=None, values=values)
        else:
            await objects.ensure_idle('scene', target)
            await write_fields(objects, target, values)
        await objects.bind_assets(target, assets)
        return target

    async def import_episode(self, request: ImportEpisode):
        files = PackageFiles(request.directory, self.allowed_root)
        manifest, screenplay, assets, board = files.episode()
        fingerprint = digest({k: digest(v.hex()) for k, v in files.files.items()})
        fingerprint = digest({'tool': 'import_episode', 'files': fingerprint})
        async with in_transaction():
            previous = await self.replay(request.request_id, fingerprint)
            if previous:
                files.receipt(previous)
                return previous
            work = manifest.work.id
            episode = manifest.episode.id
            mapping = await WorkSyncObject.get_or_none(work_id=self.work_key(work), episode_id='', kind='work', stable_id=work)
            try:
                preferences = validate_project_config(manifest.model_dump(exclude_none=True,
                    include={"style_key", "custom_style_prompt", "storyboard_enabled"}))
            except HTTPException as error:
                raise ValueError(error.detail) from error
            if mapping is None:
                project = await novel_controller.create(
                    NovelCreate(name=manifest.work.name, aspect_ratio=manifest.aspect_ratio, author="Agent 创建", **preferences),
                    team_id=self.ctx.team_id if self.ctx else None, created_by=self.ctx.user.id if self.ctx else None)
                await self.register(work, '', 'work', work, project.id, manifest.work.model_dump())
            else:
                project = await self.project(work)
            async with project_write(project.id):
                # Recheck after acquiring the canonical project lock.
                previous = await self.replay(request.request_id, fingerprint)
                if previous:
                    files.receipt(previous)
                    return previous
                if await WorkSyncObject.filter(work_id=self.work_key(work), episode_id=episode, kind='episode').exists():
                    raise SyncConflict('episode_exists', message='已导入的集不能整集覆盖；请使用单镜同步')
                if await Chapter.filter(novel_id=project.id, number=manifest.number).exists():
                    raise SyncConflict('episode_number_exists')
                for asset in assets:
                    for obj in [asset, *asset.variants]:
                        validate_asset_design(obj.prompt)
                urls = files.archive(self.archive_root)
                objects = CreationObjects(project.id)
                for asset in assets:
                    payload = asset.model_dump()
                    existing = await WorkSyncObject.get_or_none(work_id=self.work_key(work), episode_id='', kind='asset', stable_id=asset.id)
                    if existing:
                        target = await objects.get('asset', existing.local_id)
                        if existing.payload['source'] != payload or existing.payload['version'] != await objects.recovery_version(target):
                            raise SyncConflict('asset_changed', asset_id=asset.id)
                    else:
                        images = {m.role: urls[m.path] for m in asset.media}
                        target = await objects.create_setting({'canonical_name': asset.name,
                            'asset_type': {'person': 1, 'group': 1, 'scene': 2, 'item': 3}[asset.kind],
                            'description': asset.description, 'base_traits': asset.prompt, 'aliases': asset.aliases,
                            'main_image': images.get('main'), 'angle_image_1': images.get('angle_1'),
                            'angle_image_2': images.get('angle_2'),
                            'metadata': {'reference_layout': GROUP_PORTRAIT if asset.kind == 'group' else CHARACTER_TURNAROUND,
                                         'work_package': payload, 'imported_media': [
                                {**m.model_dump(), 'url': urls[m.path]} for m in asset.media]}})
                        await self.register(work, '', 'asset', asset.id, target.id,
                            {'source': payload, 'version': await objects.recovery_version(target)})
                        for variant in asset.variants:
                            obj = await objects.create_variant(target.id, {'name': variant.name,
                                'description': variant.description, 'base_traits': variant.prompt,
                                'images': [urls[m.path] for m in variant.media]})
                            await self.register(work, '', 'variant', variant.id, obj.id,
                                                {'asset_id': asset.id, 'source': variant.model_dump(),
                                                 'version': await objects.recovery_version(obj)})
                chapter = await chapter_controller.create(ChapterCreate(novel_id=project.id, number=manifest.number,
                    name=manifest.episode.name, screenplay=screenplay,
                    content=files.files[manifest.source_text].decode("utf-8-sig") if manifest.source_text else ""))
                await self.register(work, episode, 'episode', episode, chapter.id,
                                    {'manifest': manifest.model_dump(), 'archive': urls,
                                     'scenes': [s.model_dump() for s in board.scenes]})
                for shot in board.shots:
                    target = await self.persist_shot(objects, chapter.id, work, episode, shot, urls, language=manifest.language)
                    await self.register(work, episode, 'shot', shot.id, target.id, shot.model_dump())
                await self.link_episode_assets(work, chapter, assets, board, objects)
                receipt = await self.read_episode(ReadEpisode(work_id=work, episode_id=episode))
                receipt['request_id'] = request.request_id
                await WorkSyncRequest.create(request_id=self.request_key(request.request_id), payload_hash=fingerprint, receipt=receipt)
        files.receipt(receipt)
        return receipt

    async def read_episode(self, request: ReadEpisode):
        project = await self.project(request.work_id)
        episode = await self.mapping(request.work_id, request.episode_id, 'episode', request.episode_id)
        chapter = await Chapter.get_or_none(id=episode.local_id, novel_id=project.id)
        if chapter is None:
            raise ValueError('集不存在')
        shots = []
        for row in await WorkSyncObject.filter(work_id=self.work_key(request.work_id), episode_id=request.episode_id, kind='shot'):
            target = await Scene.get_or_none(id=row.local_id, chapter_id=chapter.id)
            if target:
                item = {'shot_id': row.stable_id, 'local_id': target.id, 'sequence': target.sequence,
                        'version': await CreationObjects.recovery_version(target)}
                if request.shot_id == row.stable_id:
                    item.update(description=target.description, prompt=target.prompt, duration=target.duration,
                                structure=target.prompt_params, metadata=target.metadata,
                                asset_ids=await target.assets.all().values_list('id', flat=True))
                if request.shot_id is None or request.shot_id == row.stable_id:
                    shots.append(item)
        if request.shot_id is not None and not shots:
            raise ValueError('镜头不存在或已移除')
        return {'status': 'ok', 'format_version': 1, 'work_id': request.work_id,
                'episode_id': request.episode_id, 'novel_id': project.id, 'chapter_id': chapter.id,
                'location': self.location(project.id, chapter.id, chapter.number),
                'project_settings': {'style_key': project.style_key, 'custom_style_prompt': project.custom_style_prompt,
                                     'storyboard_enabled': project.storyboard_enabled},
                'archive': episode.payload['archive'], 'shots': sorted(shots, key=lambda s: s['sequence'])}

    async def update_shot(self, request: UpdateShot):
        files = PackageFiles(request.directory, self.allowed_root)
        if not set(request.changes) <= (set(Shot.model_fields) - {'id'}):
            raise ValueError('不支持的镜头变更字段')
        project = await self.project(request.work_id)
        async with project_write(project.id):
            if 'media' in request.changes:
                for media in request.changes['media']:
                    files.read(media['path'])
            fingerprint = digest({'tool': 'update_shot', **request.model_dump(exclude={'directory'}),
                                  'media_bytes': {k: digest(v.hex()) for k, v in files.files.items()}})
            previous = await self.replay(request.request_id, fingerprint)
            if previous:
                files.receipt(previous)
                return previous
            episode = await self.mapping(request.work_id, request.episode_id, 'episode', request.episode_id)
            row = await self.mapping(request.work_id, request.episode_id, 'shot', request.shot_id)
            objects = CreationObjects(project.id)
            target = await objects.get('scene', row.local_id)
            if target.chapter_id != episode.local_id:
                raise ValueError('镜头已移到其他集')
            current = await objects.recovery_version(target)
            if current != request.base_version:
                raise SyncConflict('version_conflict', shot_id=request.shot_id, base_version=request.base_version,
                                   current_version=current, message='猫影内容已修改，请先读取、对比并由用户确认合并，不能自动覆盖')
            shot = Shot.model_validate({**row.payload, 'description': target.description or '',
                'prompt': target.prompt or '', 'duration': target.duration,
                'structure': target.prompt_params or {}, **request.changes})
            if shot.scene_id not in {s['id'] for s in episode.payload['scenes']}:
                raise ValueError('未登记的场 ID')
            # Unchanged archived media do not require the source files to still exist.
            urls = {m['path']: m['url'] for m in (target.metadata or {}).get('imported_media', [])}
            if 'media' in request.changes:
                files.media(shot)
                urls = files.archive(self.archive_root)
            await self.persist_shot(objects, target.chapter_id, request.work_id, request.episode_id, shot, urls, target,
                                    preserve_visual='visual' not in request.changes, sync_media='media' in request.changes,
                                    language=episode.payload['manifest'].get('language', 'zh'))
            row.payload = shot.model_dump()
            await row.save(update_fields=['payload'])
            receipt = await self.read_episode(ReadEpisode(work_id=request.work_id, episode_id=request.episode_id))
            receipt['request_id'] = request.request_id
            await WorkSyncRequest.create(request_id=self.request_key(request.request_id), payload_hash=fingerprint, receipt=receipt)
        files.receipt(receipt)
        return receipt
