"""Retain valid asset designs while repairing only missing or invalid entries."""

from services.extraction.extractor import validate_asset_design
from utils.messages import localized_message
from pydantic import Field, SkipValidation, ValidationError, create_model


class AssetExtractionValidationError(ValueError):
    error_code = 'asset_extraction_validation_error'

    def __init__(self, issues):
        super().__init__(localized_message('资产设定检查未通过，已保留候选：{p0}', p0='；'.join(issues)))


class AssetCandidateValidator:
    def __init__(self, output_type=None, asset_scope=()):
        self.output_type = output_type
        self.asset_scope = set(asset_scope)
        self.extra = {}
        self.draft_type = None
        if output_type:
            fields = {}
            for name in ('persons', 'scenes', 'items'):
                item_type = output_type.model_fields[name].annotation.__args__[0]
                repair_type = create_model(item_type.__name__ + 'Repair', __base__=item_type,
                    repair_of=(str | None, Field(None, description='Original failed asset name or #slot; omit for initial output')))
                fields[name] = (list[SkipValidation[repair_type]], Field(...))
            self.draft_type = create_model(output_type.__name__ + 'Candidate', __base__=output_type, **fields)
        self.accepted = {name: {} for name in ('persons', 'scenes', 'items')}
        self.pending = {}
        self.issues = []

    @staticmethod
    def identity(data, fallback=''):
        variant = data.get('variant')
        form = ''
        if variant is not None:
            form = (str(variant.get('name') or '').strip() if isinstance(variant, dict) else '') or fallback or '#variant'
        return str(data.get('name') or fallback).strip(), form

    @staticmethod
    def label(identity):
        name, variant = identity
        return f'{name}#{variant}' if variant else name

    def merge(self, output):
        field_types = {'persons': 1, 'scenes': 2, 'items': 3}
        known_names = {name for _, name in self.asset_scope}
        def misplaced(field, name):
            return name in known_names and (field_types[field], name) not in self.asset_scope
        for field in self.accepted:
            self.accepted[field] = {key: value for key, value in self.accepted[field].items() if not misplaced(field, key[0])}
        self.pending = {key: issue for key, issue in self.pending.items() if not misplaced(key[0], key[1])}
        if self.output_type:
            self.extra.update(output.model_dump(exclude=set(field_types), mode='json', warnings=False))
        for field in field_types:
            entries = [raw.model_dump() if hasattr(raw, 'model_dump') else raw for raw in getattr(output, field)]
            # A variant-only row may reuse its base design from this response or checkpoint.
            bases = {str(data.get('name') or '').strip(): data.get('base_traits') for data in entries
                     if isinstance(data, dict) and data.get('variant') is None and data.get('base_traits')}
            bases.update({key[0]: item.base_traits for key, item in self.accepted[field].items() if not key[1]})
            for index, (raw, entry) in enumerate(zip(getattr(output, field), entries), 1):
                data = dict(entry) if isinstance(entry, dict) else {}
                original = data.pop('repair_of', None)
                identity = self.identity(data, f'#{index}')
                name = self.label(identity)
                key = (field, *identity)
                if misplaced(field, identity[0]) or identity in self.accepted[field]:
                    continue
                if self.output_type:
                    if data.get('variant') and 'base_traits' not in data and identity[0] in bases:
                        data['base_traits'] = bases[identity[0]]
                    try:
                        item = self.output_type.model_fields[field].annotation.__args__[0].model_validate(data)
                    except ValidationError as error:
                        self.pending[key] = f'{field}/{name}: ' + '; '.join(
                            f"{'.'.join(map(str, issue['loc']))}: {issue['msg']}" for issue in error.errors(include_input=False))
                        continue
                else:
                    item = raw
                try:
                    validate_asset_design(item.base_traits)
                    if item.variant:
                        validate_asset_design(item.variant.base_traits)
                except ValueError as error:
                    self.pending[key] = f'{field}/{name}: {error}'
                else:
                    # Repairs cannot rewrite an accepted base or another accepted form.
                    self.accepted[field][identity] = item
                    self.pending.pop(key, None)
                    if original:
                        for pending in list(self.pending):
                            if pending[0] == field and (self.label(pending[1:]) == original
                                    or pending[1:] == (original, identity[1])):
                                self.pending.pop(pending)
        self.issues = list(self.pending.values())
        accepted = {field: list(items.values()) for field, items in self.accepted.items()}
        return self.output_type(**self.extra, **accepted) if self.output_type else output.model_copy(update=accepted)

    def names(self):
        return {field: [self.label(key) for key in items] for field, items in self.accepted.items()}

    def restore(self, checkpoint, output_type):
        output = output_type.model_validate(checkpoint['accepted'])
        self.extra = output.model_dump(exclude=set(self.accepted), mode='json')
        self.accepted = {field: {self.identity(item.model_dump()): item for item in getattr(output, field)}
                         for field in self.accepted}
        self.issues = list(checkpoint['issues'])
        # Old checkpoints identify pending base assets with just (field, name).
        self.pending = {tuple(key) if len(key) == 3 else (*key, ''): issue
                        for key, issue in checkpoint.get('pending', [])}
        if not self.pending and self.issues:
            for field, items in checkpoint.get('attempted', {}).items():
                if field not in self.accepted:
                    continue
                for index, item in enumerate(items, 1):
                    identity = self.identity(item, f'#{index}')
                    if identity not in self.accepted[field]:
                        self.pending[(field, *identity)] = f'{field}/{self.label(identity)}: ' + ' / '.join(self.issues)
