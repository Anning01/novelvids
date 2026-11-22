"""Map provider-constrained fields into the existing asset writer, preserving optional appearances."""

from pydantic import ValidationError

from prompts.text_tasks import render_asset_fields
from services.extraction.extractor import AssetExtractionResult, Person, Scene, Item, ExtractedVariant
from utils.messages import localized_message


def extraction_result(payload, rendering):
    def convert(value, model, kind):
        value = dict(value)
        kind = 'group' if value.get('label') == '群像' else kind
        def design(data):
            fields = data.pop('visual_fields')
            return render_asset_fields(data.pop('design'), {} if fields is None else fields,
                rendering['asset_specifications'][kind], rendering['aspect_ratio'])
        variant = value.pop('variant', None)
        if variant is not None:
            try:
                variant = {key: variant[key] for key in (
                    'existing_variant_id', 'name', 'description', 'change_reason', 'design', 'visual_fields')}
                if not isinstance(variant['design'], str) or not variant['design'].strip():
                    raise ValueError(localized_message('提示词不能为空'))
                variant['base_traits'] = design(variant)
                variant = ExtractedVariant.model_validate(variant, strict=True)
            except KeyError as error:
                raise KeyError(f'variant.{error.args[0]}') from error
            except (ValidationError, TypeError) as error:
                raise ValueError(localized_message('形态绑定格式无效')) from error
        value['base_traits'] = design(value)
        return model.model_construct(**value, variant=variant)
    result = {}
    for field, model, kind in (('persons', Person, 'person'), ('scenes', Scene, 'scene'), ('items', Item, 'item')):
        result[field] = []
        try:
            items = payload[field]
        except KeyError as error:
            raise ValueError(localized_message('资产结果转换失败：模型返回缺少字段 {p0}。', p0=field)) from error
        for index, item in enumerate(items):
            try:
                result[field].append(convert(item, model, kind))
            except KeyError as error:
                raise ValueError(localized_message(
                    '资产结果转换失败：{p0} 缺少字段 {p1}，尚未保存本次提取结果。',
                    p0=f'{field}[{index}]', p1=error.args[0])) from error
    return AssetExtractionResult.model_construct(**result)
