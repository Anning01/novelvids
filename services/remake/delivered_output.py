"""Project a delivered model reply into editable material, retaining the original in the model receipt."""
import json
import math
import re

from pydantic import ValidationError
from models.asset import Asset
from schemas.remake_asset_format import unpack_asset_rows
from schemas.remake_visible_refs import RemakeShot, RemakeShortStoryboard
from services.remake.asset_validation import render_remake_assets


def decoded(value):
    if isinstance(value, str):
        text = value.strip()
        fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.S | re.I)
        try:
            return json.loads(fenced[1] if fenced else text)
        except ValueError:
            return value
    return value


def delivered_assets(reply, snapshot, language, aspect_ratio):
    data = decoded(reply)
    inventory = {}
    name_limit = Asset._meta.fields_map["canonical_name"].max_length
    for group in ('characters', 'scenes', 'objects'):
        entries = data.get(group) if isinstance(data, dict) else None
        entries = unpack_asset_rows(entries, {'name','description','label','visual_fields','appearances'})
        rows = []
        for entry in entries if isinstance(entries, list) else ():
            if not isinstance(entry, dict) or not isinstance(entry.get('name'), str) or not entry['name'].strip():
                continue
            visual = entry.get('visual_fields')
            row = {
                'name': entry['name'].strip()[:name_limit],
                'description': entry['description'] if isinstance(entry.get('description'), str) else '',
                'visual_fields': {k: v for k, v in visual.items() if isinstance(v, str)} if isinstance(visual, dict) else {},
            }
            if isinstance(entry.get('label'), str):
                row['label'] = entry['label']
            spans = entry.get('appearances')
            if isinstance(spans, list):
                row['appearances'] = [span for span in spans if isinstance(span,dict) and
                    all(isinstance(span.get(k), (int,float)) and math.isfinite(span[k]) for k in ('start_seconds','end_seconds'))]
            rows.append(row)
        inventory[group] = rows
    return render_remake_assets(inventory, snapshot, language, aspect_ratio)


def raw_shot(value):
    text = value if isinstance(value,str) else None
    if isinstance(value,dict) and isinstance(value.get('prompt'),str):
        text = value['prompt']
    refs = []
    if isinstance(value, dict) and isinstance(value.get('asset_refs'), list):
        for ref in value['asset_refs']:
            if not isinstance(ref, dict) or ref.get('asset_type') not in ('character', 'scene', 'object'):
                continue
            name = ref.get('asset_name')
            if isinstance(name, str) and name.strip():
                refs.append({'asset_id': str(ref.get('asset_id') or len(refs) + 1), 'asset_type': ref['asset_type'],
                             'asset_name': name, 'visual_description': ref.get('visual_description') if isinstance(ref.get('visual_description'), str) else ''})
    return {'source_prompt_text':text or json.dumps(value,ensure_ascii=False,indent=2),
            'asset_refs':refs, 'actions':[], 'transition':''}


def delivered_shot(reply):
    value = decoded(reply)
    try:
        return RemakeShot.model_validate(value).model_dump(mode='json')
    except ValidationError:
        return raw_shot(value)


def delivered_batch(reply, intervals):
    data = decoded(reply)
    rows = data.get('shots') if isinstance(data, dict) else data
    if not isinstance(rows, list):
        # Unsegmented prose can be attributed to a single requested interval.
        # For multiple intervals its complete text stays in the batch receipt.
        return {intervals[0]['sequence']:raw_shot(rows if rows is not None else data)} if len(intervals) == 1 else {}
    spans = {span['sequence']:span for span in intervals}
    result = {}
    for position, row in enumerate(rows):
        index = row.get('sequence') if isinstance(row,dict) else None
        if not isinstance(index,int):
            index = intervals[position]['sequence'] if position < len(intervals) else None
        if index not in spans or index in result:
            continue
        try:
            # A fully structured row can use the professional editor. Otherwise keep its authored text.
            batch = RemakeShortStoryboard.model_validate({'looks':data.get('looks',[]) if isinstance(data,dict) else [], 'shots':[row]})
            result.update(batch.materialize([spans[index]]))
        except ValueError:
            result[index] = raw_shot(row)
    return result
