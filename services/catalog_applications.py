"""Apply stable library references using existing project write services."""
from fastapi import HTTPException
from auth.deps import ensure_novel_access
from models.novel import Novel
from models.asset import Asset
from models.asset_variant import AssetVariant
from models.resource_library import ProjectResource
from services.resource_catalog import resource_catalog
from services.audio_references import audio_reference_accessible
from utils.messages import localized_message as msg


def metadata_dict(value):
    return value if isinstance(value,dict) else {}


def bound_voice_metadata(value, voice):
    values={'voice':voice.nickname,'voice_reference_id':voice.id}
    previous=metadata_dict(value)
    if isinstance(previous.get('editor_form'),dict):
        return {**previous,**values,'editor_form':{**previous['editor_form'],**values}}
    return {**previous,**values}


async def apply_catalog_resource(team,ctx,key,payload):
    await ensure_novel_access(payload.novel_id,ctx)
    novel=await Novel.get_or_none(id=payload.novel_id)
    if novel is None or (not ctx.is_super_admin and (novel.team_id or 0)!=team):
        raise HTTPException(404,msg('项目不存在'))
    if payload.chapter_id:
        from models.chapter import Chapter
        if not await Chapter.filter(id=payload.chapter_id,novel_id=novel.id).exists():
            raise HTTPException(404,msg('章节不存在'))
    catalog,row=await resource_catalog.get(team,ctx,key)
    if catalog=='media':
        link,_=await ProjectResource.get_or_create(novel_id=novel.id,resource_id=row.id)
        return {'novel_id':novel.id,'resource_key':key,'link_id':link.id}
    if catalog=='voice':
        if not await audio_reference_accessible(row,team_id=novel.team_id,created_by=novel.created_by):
            raise HTTPException(404,msg('选择的旁白音色不存在'))
        if payload.asset_id:
            target=await Asset.get_or_none(id=payload.asset_id,novel_id=novel.id,asset_type=1)
            if target is None:
                raise HTTPException(404,msg('资产不存在'))
            from controllers.asset import asset_controller
            if payload.variant_id:
                from schemas.asset_variant import AssetVariantPatch
                variant=await AssetVariant.get_or_none(id=payload.variant_id,asset_id=target.id)
                if variant is None:
                    raise HTTPException(404,msg('资产形态不存在'))
                await asset_controller.patch_variant(target.id,variant.id,AssetVariantPatch(metadata=bound_voice_metadata(variant.metadata,row)))
            else:
                from schemas.asset import AssetPatch
                await asset_controller.patch(target.id,AssetPatch(metadata=bound_voice_metadata(target.metadata,row)))
        else:
            if payload.variant_id:
                raise HTTPException(422,msg('请先选择所属角色'))
            from controllers.novel import novel_controller
            from schemas.novel import NovelPatch
            await novel_controller.patch(novel.id,NovelPatch(narrator_audio_reference_id=row.id))
        return {'novel_id':novel.id,'resource_key':key}
    from controllers._creation import creation_write
    from services.creation_objects import CreationObjects
    if catalog=='human':
        name=(payload.canonical_name or row.occupation or row.asset_id).strip()
        values={'asset_type':1,'canonical_name':name,'main_image':row.image_url,'image_source':2,
                'is_global':False,'metadata':{'source_asset_id':row.asset_id,'library_source':'public',
                'gender':row.gender,'age':row.age,'occupation':row.occupation,'country':row.country}}
        variants=[]
    else:
        name=(payload.canonical_name or row.canonical_name).strip()
        values={field:getattr(row,field) for field in ('asset_type','canonical_name','aliases','description','base_traits','main_image','angle_image_1','angle_image_2','image_source')}
        values.update(is_global=False,metadata={**metadata_dict(row.metadata),'source_asset_id':row.id,'library_source':'team'})
        values['canonical_name']=name
        variants=await AssetVariant.filter(asset_id=row.id)
        from models.audio_reference import AudioReference
        for metadata in [values['metadata'],*[variant.metadata for variant in variants]]:
            reference_id=metadata_dict(metadata).get('voice_reference_id')
            if reference_id:
                voice=await AudioReference.get_or_none(id=reference_id,is_active=True)
                if voice is None or not await audio_reference_accessible(voice,team_id=novel.team_id,created_by=novel.created_by):
                    raise HTTPException(409,msg('角色绑定了目标项目不可用的音色，请先核对'))
    if not name:
        raise HTTPException(422,msg('名称不能为空'))
    async with creation_write(novel.id):
        objects=CreationObjects(novel.id)
        existing=await Asset.filter(novel_id=novel.id,canonical_name=name,asset_type=values['asset_type']).first()
        if existing:
            if not (catalog == 'asset' and existing.id == row.id) and (existing.metadata or {}).get('source_asset_id')!=values['metadata']['source_asset_id']:
                raise HTTPException(409,msg('项目中已有同名角色，请在项目中核对'))
            target=existing
        else:
            target=await objects.create_setting(values)
            for variant in variants:
                await objects.create_variant(target.id,{field:getattr(variant,field) for field in ('name','description','base_traits','images','metadata')})
    if payload.chapter_id:
        from controllers.asset import asset_controller
        await asset_controller.reuse_in_chapter(target.id,payload.chapter_id)
    return {'novel_id':novel.id,'resource_key':key,'asset_id':target.id}
