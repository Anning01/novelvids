"""Typed team catalog over existing media, voices and character identities."""
import re
from fastapi import HTTPException
from tortoise.expressions import Q
from tortoise.transactions import in_transaction
from tortoise.functions import Lower
from auth.deps import AuthContext, ensure_novel_access
from models.asset import Asset
from models.audio_reference import AudioReference
from models.digital_human import DigitalHuman
from models.novel import Novel
from models.resource_library import VideoResource, ResourcePlacement
from schemas.media_library import AudioReferenceOut, DigitalHumanOut
from services.audio_references import audio_reference_scope_query
from services.oss import resolve_media_url
from services.resource_permissions import owner_scope, readable_scope, public_scope, is_public_resource, ensure_resource_write, resource_owner
from controllers.resource_library import resource_library_controller as library, resource_dict
from services.resource_references import resource_for
from utils.messages import localized_message as msg

MEDIA_KINDS = ('video', 'image', 'bgm', 'sound', 'sticker')
CATALOG_KINDS = (*MEDIA_KINDS, 'voice', 'character')


def parse_key(key: str):
    match = re.fullmatch(r'(media|voice|human|asset):([1-9][0-9]*)', key)
    if not match:
        raise HTTPException(422, msg('资源标识无效'))
    return match[1], int(match[2])


def entry(catalog, row, kind, name, url, *, origin='team', folder_id=0, **extra):
    return {'key': f'{catalog}:{row.id}', 'catalog': catalog, 'id': row.id, 'kind': kind,
            'name': name, 'url': url or '', 'origin': origin, 'folder_id': folder_id,
            'created_at': row.created_at, 'editable': origin == 'team', **extra}


class ResourceCatalog:
    async def list(self, team: int, ctx: AuthContext, *, kind='all', folder_id=None, search='', origin='all', page=1, page_size=24, sort='recent', gender='', country='', age='', occupation=''):
        queries = []
        media = VideoResource.filter(readable_scope(team), state__in=['ready', 'delete_failed', 'deleting'])
        if kind in MEDIA_KINDS:
            media = media.filter(kind=kind)
        if search:
            media = media.filter(name__icontains=search)
        if folder_id is not None:
            await library.folder(team, folder_id, readable=True)
            media = media.filter(folder_id=folder_id)
        if kind == 'all' or kind in MEDIA_KINDS:
            if origin == 'system':
                media = media.filter(public_scope())
            elif origin == 'team':
                media = media.exclude(public_scope())
            if origin != 'personal':
                queries.append(('media', media))
        placement = ResourcePlacement.filter(Q() if team is None else Q(team_id__in=[team, 0]))
        if folder_id is not None:
            placement = placement.filter(folder_id=folder_id)
        voice_query = AudioReference.filter(is_active=True)
        if not ctx.is_super_admin or team is not None:
            voice_query = voice_query.filter(audio_reference_scope_query(team_id=team or None, created_by=ctx.user.id if ctx.user else None))
        if origin == 'system':
            voice_query = voice_query.filter(Q(source='system') | public_scope())
        elif origin == 'team':
            voice_query = voice_query.filter(source='upload').exclude(public_scope())
            if team is not None:
                voice_query = voice_query.filter(team_id=team)
        elif origin == 'personal':
            voice_query = voice_query.filter(source='upload', team_id=None).exclude(public_scope())
        if search:
            voice_query = voice_query.filter(nickname__icontains=search)
        if gender:
            voice_query = voice_query.filter(gender__in=self.genders(gender))
        if folder_id is not None:
            ids = await placement.filter(catalog='voice').values_list('source_id', flat=True)
            if folder_id == 0:
                assigned = await ResourcePlacement.filter(owner_scope(team), catalog='voice').exclude(folder_id=0).values_list('source_id', flat=True)
                voice_query = voice_query.exclude(id__in=assigned)
            else:
                voice_query = voice_query.filter(id__in=ids)
        if kind in {'all', 'voice'}:
            queries.append(('voice', voice_query))
        if kind in {'all', 'character'}:
            if origin in {'all', 'system'}:
                human = DigitalHuman.filter(is_active=True)
                assigned = ResourcePlacement.filter(catalog='human')
                if folder_id == 0:
                    human = human.exclude(id__in=await assigned.exclude(folder_id=0).values_list('source_id',flat=True))
                elif folder_id is not None:
                    human = human.filter(id__in=await assigned.filter(folder_id=folder_id).values_list('source_id',flat=True))
                if search:
                    human = human.filter(Q(occupation__icontains=search) | Q(asset_id__icontains=search) | Q(country__icontains=search))
                if gender:
                    human = human.filter(gender__in=self.genders(gender))
                if country:
                    human = human.filter(country=country)
                if occupation:
                    human = human.filter(occupation=occupation)
                if age:
                    ranges = {'under-20': (0,19), '20-29':(20,29), '30-39':(30,39), '40-59':(40,59), '60-plus':(60,200)}
                    if age in ranges:
                        human = human.filter(age__gte=ranges[age][0], age__lte=ranges[age][1])
                queries.append(('human', human))
        asset_placements = {}
        if kind in {'all', 'character', 'image'} and origin in {'all', 'team', 'system'}:
            ids = await ResourcePlacement.filter(catalog='asset', **({'folder_id':folder_id} if folder_id is not None else {})).values_list('source_id', flat=True)
            assets = Asset.filter(id__in=ids, asset_type__in=[1,2,3])
            if team is not None:
                assets = assets.filter(Q(novel__team_id=team or None) | public_scope('novel__'))
            if origin == 'system':
                assets = assets.filter(public_scope('novel__'))
            elif origin == 'team':
                assets = assets.exclude(public_scope('novel__'))
            if kind != 'all':
                assets = assets.filter(asset_type__in=[1] if kind == 'character' else [2,3])
            asset_placements = {row.source_id:row for row in await placement.filter(catalog='asset')}
            queries.append(('asset', assets.only('id','novel_id','asset_type','canonical_name','main_image','description','metadata','created_at')))
        # Only fetch the prefix needed to merge independently ordered legacy catalogs.
        # Each provider remains paginated; no media bytes or private prompts are loaded.
        rows, total, batches = [], 0, []
        for catalog, query in queries:
            if catalog == 'asset':
                # Catalog aliases and legacy traits live outside the source's searchable columns.
                assets = [row for row in await query if self.matches_asset(row,asset_placements.get(row.id),search,gender,country,age,occupation)]
                total += len(assets)
                batches.extend((catalog,row) for row in assets)
                continue
            count = await query.count()
            total += count
            order = 'nickname' if catalog == 'voice' else 'occupation' if catalog == 'human' else 'canonical_name' if catalog == 'asset' else 'name'
            if sort == 'name':
                query=query.annotate(catalog_order=Lower(order))
            batch = await query.order_by('catalog_order' if sort == 'name' else '-created_at', 'id' if sort == 'name' else '-id').limit(page * page_size)
            batches.extend((catalog,row) for row in batch)
        placements = {(row.catalog,row.source_id): row for row in await ResourcePlacement.filter(owner_scope(team),source_id__in=[row.id for catalog,row in batches if catalog != 'media'])}
        for catalog,row in batches:
            rows.append(await self.describe(team,catalog,row,placement=placements.get((catalog,row.id)),ctx=ctx))
        rows.sort(key=lambda item: (item['name'].lower(),item['catalog'],item['id']) if sort == 'name' else (item['created_at'],item['catalog'],item['id']), reverse=sort != 'name')
        offset = (page-1)*page_size
        return {'items': rows[offset:offset+page_size], 'pagination': {'page':page,'page_size':page_size,'total':total,'pages':(total+page_size-1)//page_size}}

    @staticmethod
    def genders(value):
        return {'male':['男','男性'],'female':['女','女性']}.get(value,[value])

    @classmethod
    def matches_asset(cls,row,placement,search,gender,country,age,occupation):
        metadata=row.metadata if isinstance(row.metadata,dict) else {}
        name=(placement.name if placement else '') or row.canonical_name
        if search.casefold() not in name.casefold():
            return False
        if gender and metadata.get('gender') not in cls.genders(gender):
            return False
        if country and metadata.get('country') != country:
            return False
        if occupation and metadata.get('occupation') != occupation:
            return False
        if age:
            ranges={'under-20':(0,19),'20-29':(20,29),'30-39':(30,39),'40-59':(40,59),'60-plus':(60,200)}
            try:
                number=int(metadata.get('age'))
            except (ValueError,TypeError):
                return False
            if age not in ranges or not ranges[age][0] <= number <= ranges[age][1]:
                return False
        return True

    async def describe(self, team, catalog, row, *, placement=False, ctx=None):
        result = await self._describe(team, catalog, row, placement=placement)
        if ctx is not None:
            public = await is_public_resource(row)
            owner = await resource_owner(row)
            can_write = ctx.user is None or ctx.is_super_admin or (ctx.membership and ctx.membership.role in {'admin', 'creator'})
            editable = bool(can_write and (ctx.is_super_admin or not public and result['editable'] or ctx.user is None))
            result.update(editable=editable, deletable=editable, is_public=public, team_id=getattr(owner, 'team_id', 0))
            if public:
                result['origin'] = 'system'
        return result

    async def _describe(self, team, catalog, row, *, placement=False):
        if catalog == 'media':
            return entry(catalog,row,row.kind,row.name,resolve_media_url(row.storage_ref),**{k:v for k,v in resource_dict(row).items() if k not in {'id','kind','name','url','created_at','folder_id'}},folder_id=row.folder_id)
        if placement is False:
            owner = await resource_owner(row)
            placement = await ResourcePlacement.filter(team_id=getattr(owner, 'team_id', None) or 0,catalog=catalog,source_id=row.id).first()
        folder = placement.folder_id if placement else 0
        if catalog == 'voice':
            raw = AudioReferenceOut.model_validate(row).model_dump(mode='json')
            origin = 'system' if row.source == 'system' else 'team' if row.team_id is not None or (team == 0 and row.created_by is None) else 'personal'
            return entry(catalog,row,'voice',row.nickname,raw['audio_url'],origin=origin,folder_id=folder,
                         poster_url=raw['avatar_url'],duration=row.duration or 0,gender=row.gender,asset_id=row.asset_id,payload=raw)
        if catalog == 'human':
            raw = DigitalHumanOut.model_validate(row).model_dump(mode='json')
            return entry(catalog,row,'character',row.occupation,raw['image_url'],origin='system',folder_id=folder,poster_url=raw['image_url'],asset_id=row.asset_id,payload=raw,
                         gender=row.gender,country=row.country,age=row.age,occupation=row.occupation)
        metadata=row.metadata if isinstance(row.metadata,dict) else {}
        return entry(catalog,row,'character' if row.asset_type == 1 else 'image',(placement.name if placement else None) or row.canonical_name,resolve_media_url(row.main_image),folder_id=folder,
                     poster_url=resolve_media_url(row.main_image),asset_type=row.asset_type,source_asset_id=row.id,description=row.description or '',
                     **{key:metadata[key] for key in ('country','gender','occupation','age') if isinstance(metadata.get(key),(str,int))})

    async def get(self, team, ctx, key, *, writable=False):
        catalog, ident = parse_key(key)
        row = None
        if catalog == 'media':
            row = await resource_for(None if ctx.is_super_admin else team,ident,kind=None,ready=not writable)
        elif catalog == 'voice':
            query = AudioReference.filter(id=ident,is_active=True)
            if not ctx.is_super_admin:
                query = query.filter(audio_reference_scope_query(team_id=team or None,created_by=ctx.user.id if ctx.user else None))
            row = await query.first()
            if row and writable and not ctx.is_super_admin and row.team_id != team and not (team == 0 and row.team_id is None and row.created_by is None and ctx.user is None):
                raise HTTPException(403,msg('系统或个人历史资源不能修改团队目录'))
        elif catalog == 'human':
            row = await DigitalHuman.get_or_none(id=ident,is_active=True)
        else:
            if await ResourcePlacement.filter(catalog='asset',source_id=ident).exists():
                query = Asset.filter(id=ident)
                if not ctx.is_super_admin:
                    query = query.filter(Q(novel__team_id=team or None) | public_scope('novel__'))
                row = await query.first()
        if row is None:
            raise HTTPException(404,msg('资源不存在或无权访问'))
        if writable:
            await ensure_resource_write(ctx, [row])
        return catalog,row

    async def rename(self,team,ctx,key,name):
        if ctx.is_super_admin:
            team = None
        catalog,row = await self.get(team,ctx,key,writable=True)
        if catalog in {'voice','asset','human'} and len(name)>100:
            raise HTTPException(422,msg('名称不能超过 100 个字符'))
        if catalog == 'media':
            row.name=name;await row.save(update_fields=['name','updated_at'])
        elif catalog == 'voice':
            row.nickname=name;await row.save(update_fields=['nickname','updated_at'])
        elif catalog == 'human':
            row.occupation=name;await row.save(update_fields=['occupation','updated_at'])
        else:
            await ResourcePlacement.filter(owner_scope(team),catalog=catalog,source_id=row.id).update(name=name)
        return await self.describe(team,catalog,row,ctx=ctx)

    async def move(self,team,ctx,keys,folder_id):
        if ctx.is_super_admin:
            team = None
        async with in_transaction():
            if folder_id:
                from models.resource_library import ResourceFolder
                await ResourceFolder.filter(team_id=team,id=folder_id).select_for_update()
            await library.folder(team,folder_id)
            values = [await self.get(team,ctx,key,writable=True) for key in keys]
            media = [row.id for catalog,row in values if catalog == 'media']
            if media:
                await library.move(team,media,folder_id)
            for catalog,row in values:
                if catalog != 'media':
                    owner = await resource_owner(row)
                    placement_team = getattr(owner, 'team_id', None) or 0
                    if folder_id:
                        target = await library.folder(None if ctx.is_super_admin else team, folder_id)
                        if target.team_id != placement_team:
                            raise HTTPException(422,msg('请选择资源所属团队的文件夹'))
                    placement,_ = await ResourcePlacement.get_or_create(team_id=placement_team,catalog=catalog,source_id=row.id)
                    placement.folder_id=folder_id;await placement.save(update_fields=['folder_id','updated_at'])

    async def delete(self, team, ctx, keys):
        if ctx.is_super_admin:
            team = None
        # Authorize the entire batch before any database or storage deletion.
        values = [await self.get(team, ctx, key, writable=True) for key in keys]
        results = []
        media = [row for catalog, row in values if catalog == 'media']
        if any(row.state in {'uploading', 'source'} for row in media):
            raise HTTPException(409, msg('部分资源正在上传或无法删除'))
        for owner in {row.team_id for row in media}:
            results.extend(await library.delete_resources(owner, [row.id for row in media if row.team_id == owner]))
        async with in_transaction():
            for catalog, row in values:
                if catalog in {'voice', 'human'}:
                    row.is_active = False
                    await row.save(update_fields=['is_active', 'updated_at'])
                if catalog != 'media':
                    await ResourcePlacement.filter(owner_scope(team), catalog=catalog, source_id=row.id).delete()
                    results.append({'id': row.id, 'deleted': True})
        return results

    async def publish_asset(self,team,ctx,asset_id,folder_id=0):
        row=await Asset.get_or_none(id=asset_id)
        if row is None:
            raise HTTPException(404,msg('资产不存在'))
        if row.asset_type not in {1,2,3}:
            raise HTTPException(422,msg('不支持此资产类型'))
        await ensure_novel_access(row.novel_id,ctx)
        novel=await Novel.get(id=row.novel_id).only('id','team_id')
        if not ctx.is_super_admin and (novel.team_id or 0)!=team:
            raise HTTPException(404,msg('资源不存在或无权访问'))
        team = novel.team_id or 0
        await library.folder(team,folder_id)
        placement,_=await ResourcePlacement.get_or_create(team_id=team,catalog='asset',source_id=row.id)
        placement.folder_id=folder_id;await placement.save(update_fields=['folder_id'])
        return await self.describe(team,'asset',row)


resource_catalog=ResourceCatalog()
