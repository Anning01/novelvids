"""Map provider-constrained fields into the existing asset writer, without revalidation."""

from prompts.text_tasks import render_asset_fields
from services.extraction.extractor import AssetExtractionResult, Person, Scene, Item, ExtractedVariant


def extraction_result(payload, rendering):
    def convert(value, model, kind):
        value = dict(value)
        kind = 'group' if value.get('label') == '群像' else kind
        def design(data):
            return render_asset_fields(data.pop('design'), data.pop('visual_fields'),
                rendering['asset_specifications'][kind], rendering['aspect_ratio'])
        variant = value.pop('variant')
        if variant is not None:
            variant = dict(variant)
            variant['base_traits'] = design(variant)
            variant = ExtractedVariant.model_construct(**variant)
        value['base_traits'] = design(value)
        return model.model_construct(**value, variant=variant)
    return AssetExtractionResult.model_construct(**{
        field: [convert(item, model, kind) for item in payload[field]]
        for field, model, kind in (('persons', Person, 'person'), ('scenes', Scene, 'scene'), ('items', Item, 'item'))})
