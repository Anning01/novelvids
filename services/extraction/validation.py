"""Retain valid asset designs while repairing only missing or invalid entries."""

from services.extraction.extractor import validate_asset_design
from utils.messages import localized_message


class AssetExtractionValidationError(ValueError):
    error_code = 'asset_extraction_validation_error'

    def __init__(self, issues):
        super().__init__(localized_message('资产设定检查未通过，已保留候选：{p0}', p0='；'.join(issues)))


class AssetCandidateValidator:
    def __init__(self):
        self.accepted = {name: {} for name in ('persons', 'scenes', 'items')}
        self.pending = {}
        self.issues = []

    def merge(self, output, snapshot, language, aspect_ratio):
        for field, kind in (('persons', 'person'), ('scenes', 'scene'), ('items', 'item')):
            for item in getattr(output, field):
                name = item.name.strip()
                key = (field, name)
                # A later repair cannot rewrite a design that already passed.
                if name in self.accepted[field]:
                    continue
                asset_kind = 'group' if kind == 'person' and item.label == '群像' else kind
                try:
                    validate_asset_design(item.base_traits, asset_kind, snapshot, language, aspect_ratio)
                    if item.variant:
                        validate_asset_design(item.variant.base_traits, asset_kind, snapshot, language, aspect_ratio)
                except ValueError as error:
                    self.pending[key] = f'{field}/{name}: {error}'
                else:
                    self.accepted[field][name] = item
                    self.pending.pop(key, None)
        self.issues = list(self.pending.values())
        return output.model_copy(update={field: list(items.values()) for field, items in self.accepted.items()})

    def names(self):
        return {field: list(items) for field, items in self.accepted.items()}
