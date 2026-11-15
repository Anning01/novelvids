"""Shared image dependencies for buttons, agent jobs and imported asset graphs."""
from pydantic import BaseModel, Field, ConfigDict

from models.asset import Asset
from models.asset_variant import AssetVariant
from models.ai_task import AiTask
from services.creation_agent.waiting import WaitingForDependencies

REFERENCE_KEY = 'generation_reference_assets'


async def dependency_has_failed(asset_id, variant_id):
    for task in await AiTask.filter(task_type=2).order_by('-created_at'):
        params = task.request_params or {}
        if params.get('asset_id') == asset_id and params.get('variant_id') == variant_id:
            return task.status in {4, 5}
    return False


class ImageReference(BaseModel):
    model_config = ConfigDict(extra='forbid')
    asset_id: int = Field(gt=0, strict=True)
    variant_id: int | None = Field(None, gt=0, strict=True)


class ReferenceGraph:
    def __init__(self, assets, variants):
        self.assets = {asset.id: asset for asset in assets}
        self.variants = {variant.id: variant for variant in variants}

    @classmethod
    async def load(cls, novel_id):
        return cls(await Asset.filter(novel_id=novel_id),
                   await AssetVariant.filter(asset__novel_id=novel_id))

    def target(self, key):
        asset_id, variant_id = key
        asset = self.assets.get(asset_id)
        target = self.variants.get(variant_id) if variant_id is not None else asset
        if asset is None or target is None or (variant_id is not None and target.asset_id != asset_id):
            raise ValueError('参考资产或形态不存在于当前项目')
        return target

    def image(self, key):
        target = self.target(key)
        return next(iter(target.images or []), None) if key[1] is not None else target.main_image

    def references(self, key):
        target = self.target(key)
        references = [(key[0], None)] if key[1] is not None else []
        for raw in (target.metadata or {}).get(REFERENCE_KEY, []):
            ref = ImageReference.model_validate(raw)
            identity = (ref.asset_id, ref.variant_id)
            self.target(identity)
            if identity not in references:
                references.append(identity)
        return references

    def ordered(self, targets):
        ordered, visiting, visited = [], set(), set()
        def visit(key):
            if key in visiting:
                raise ValueError('参考图片依赖不能形成循环')
            if key in visited:
                return
            visiting.add(key)
            for dependency in self.references(key):
                visit(dependency)
            visiting.remove(key)
            visited.add(key)
            ordered.append(key)
        for key in targets:
            visit(key)
        return ordered

    def ready(self, key):
        self.ordered([key])
        return all(self.image(ref) for ref in self.references(key))

    def missing_ordered(self, targets):
        ordered = self.ordered(targets)
        required = set()
        def require(key):
            if self.image(key) or key in required:
                return
            required.add(key)
            for ref in self.references(key):
                require(ref)
        for key in targets:
            require(key)
        return [key for key in ordered if key in required]


async def image_dependencies_ready(params):
    if not params.get('asset_id'):
        return True
    graph = await ReferenceGraph.load(params['novel_id'])
    return graph.ready((params['asset_id'], params.get('variant_id')))


async def bind_image_dependencies(params):
    if not params.get('asset_id'):
        return
    graph = await ReferenceGraph.load(params['novel_id'])
    key = (params['asset_id'], params.get('variant_id'))
    if not graph.ready(key):
        raise WaitingForDependencies()
    images = list(params.get('reference_images') or [])
    bindings = []
    for ref in graph.references(key):
        source = graph.image(ref)
        if source not in images:
            images.append(source)
        target = graph.target(ref)
        bindings.append({'asset_id': ref[0], 'variant_id': ref[1], 'image_number': images.index(source) + 1,
                         'name': target.name if ref[1] is not None else target.canonical_name})
    if len(images) > 10:
        raise ValueError('资产设定图最多支持 10 张参考图片')
    params['reference_images'] = images
    params['image_reference_bindings'] = bindings
