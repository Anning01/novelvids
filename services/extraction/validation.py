"""Retain valid asset designs while repairing only missing or invalid entries."""

from services.extraction.extractor import validate_asset_design
from utils.messages import localized_message
from pydantic import Field, SkipValidation, ValidationError, create_model


class AssetExtractionValidationError(ValueError):
    error_code = 'asset_extraction_validation_error'

    def __init__(self, issues):
        super().__init__(localized_message('资产设定检查未通过，已保留候选：{p0}', p0='；'.join(issues)))


class AssetCandidateValidator:
    def __init__(self, output_type=None):
        self.output_type = output_type
        self.draft_type = None
        if output_type:
            fields = {}
            for name in ('persons', 'scenes', 'items'):
                item_type = output_type.model_fields[name].annotation.__args__[0]
                repair_type = create_model(item_type.__name__ + 'Repair', __base__=item_type,
                    repair_of=(str | None, Field(None, description='Original failed asset name or #slot; omit for initial output')))
                fields[name] = (list[SkipValidation[repair_type]], Field(...))
            self.draft_type = create_model(output_type.__name__ + 'Candidate', **fields)
        self.accepted = {name: {} for name in ('persons', 'scenes', 'items')}
        self.pending = {}
        self.issues = []

    def merge(self, output, snapshot, language, aspect_ratio):
        for field, kind in (('persons', 'person'), ('scenes', 'scene'), ('items', 'item')):
            for index, raw in enumerate(getattr(output, field), 1):
                original = None
                if self.output_type:
                    data = raw.model_dump() if hasattr(raw, 'model_dump') else raw
                    data = dict(data) if isinstance(data, dict) else {}
                    original = data.pop('repair_of', None)
                    name = original or str(data.get('name') or f'#{index}').strip()
                    if str(data.get('name') or '').strip() in self.accepted[field]:
                        continue
                    try:
                        item = self.output_type.model_fields[field].annotation.__args__[0].model_validate(data)
                    except ValidationError as error:
                        self.pending[(field, name)] = f'{field}/{name}: ' + '; '.join(
                            f"{'.'.join(map(str, issue['loc']))}: {issue['msg']}" for issue in error.errors(include_input=False))
                        continue
                else:
                    item = raw
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
                    if original:
                        self.pending.pop((field, original), None)
        self.issues = list(self.pending.values())
        accepted = {field: list(items.values()) for field, items in self.accepted.items()}
        return self.output_type(**accepted) if self.output_type else output.model_copy(update=accepted)

    def names(self):
        return {field: list(items) for field, items in self.accepted.items()}

    def restore(self, checkpoint, output_type):
        output = output_type.model_validate(checkpoint['accepted'])
        self.accepted = {field: {item.name.strip(): item for item in getattr(output, field)}
                         for field in self.accepted}
        self.issues = list(checkpoint['issues'])
        self.pending = {tuple(key): issue for key, issue in checkpoint.get('pending', [])}
        if not self.pending and self.issues:
            for field, items in checkpoint.get('attempted', {}).items():
                if field not in self.accepted:
                    continue
                for index, item in enumerate(items, 1):
                    name = str(item.get('name') or f'#{index}').strip()
                    if name not in self.accepted[field]:
                        self.pending[(field, name)] = f'{field}/{name}: ' + ' / '.join(self.issues)
