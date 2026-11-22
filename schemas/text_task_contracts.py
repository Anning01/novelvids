"""Platform-owned wire schemas. Creative skills never supply these contracts."""

from copy import deepcopy


def _object(properties):
    return {'type': 'object', 'properties': properties, 'required': list(properties),
            'additionalProperties': False}


_STRING = {'type': 'string'}
_STRINGS = {'type': 'array', 'items': _STRING}


def _array(item):
    return {'type': 'array', 'items': item}


def _nullable(item):
    return {'anyOf': [item, {'type': 'null'}]}


def asset_contract(specifications):
    def design(kind):
        fields = {key: _STRING for key in specifications[kind]['fields']}
        return {'design': _STRING, 'visual_fields': _object(fields) if fields else {'type': 'null'}}

    def asset(kind, labels=None):
        base = {'name': {'type': 'string', 'pattern': r'^[\s\S]{1,100}$'},
            'aliases': _STRINGS, 'description': _STRING, **design(kind),
            **({'label': {'type': 'string', 'enum': labels,
                'description': '必填，按实体填写人物、动物或群像，不能省略。'}} if labels else {})}
        variant = _nullable(_object({
            'existing_variant_id': {'type': ['integer', 'null']},
            'name': base['name'], 'description': _STRING, 'change_reason': _STRING, **design(kind),
        }))
        # Strict providers require every declared property in each object branch.
        return [_object(base), _object({'variant': variant, **base})]

    return _object({
        'persons': _array({'anyOf': [*asset('person', ['人物', '动物']), *asset('group', ['群像'])]}),
        'scenes': _array({'anyOf': asset('scene')}),
        'items': _array({'anyOf': asset('item')}),
    })


def storyboard_contract(duration_range, blocking_maps):
    duration = {'type': 'number', 'minimum': duration_range[0], 'maximum': duration_range[1]}
    time = {'type': 'number', 'minimum': 0, 'maximum': duration_range[1]}
    action = _object({'start': time, 'end': time, 'text': _STRING})
    speech = _object({'start': time, 'end': time, 'speaker': _STRING, 'delivery': _STRING, 'text': _STRING})
    point_fields = {'x': {'type': 'integer', 'minimum': 0, 'maximum': 100},
                    'y': {'type': 'integer', 'minimum': 0, 'maximum': 100}}
    point = _object(point_fields)
    layout = _object({'id': _STRING, 'name': _STRING, 'orientation': _STRING,
        'features': _array(_object({'name': _STRING,
            'kind': {'type': 'string', 'enum': ['wall', 'opening', 'path', 'footprint']}, 'points': _array(point)}))})
    blocking = _object({'orientation': _STRING, 'layout': _nullable(layout),
        'axis': _nullable(_object({'first': _STRING, 'second': _STRING})),
        'assets': _array(_object({**point_fields, 'name': _STRING, 'asset_name': {'type': ['string', 'null']},
            'end': _nullable(point), 'facing': _STRING,
            'kind': {'type': 'string', 'enum': ['person', 'animal', 'prop', 'anchor']},
            'heading': {'type': ['integer', 'null'], 'minimum': 0, 'maximum': 359}, 'route': _array(point)})),
        'cameras': _array(_object({**point_fields, 'target': _STRING,
            'frame': _nullable(_object({'left': point, 'right': point})), 'framing': _STRING, 'beat': _STRING}))})
    text_fields = ('description', 'shot_size_and_camera', 'visual_style', 'time_setting', 'environment',
        'spatial_relationships', 'visual_prose', 'format_and_look', 'lenses_and_filtration',
        'lighting_and_atmosphere', 'grade_and_palette', 'camera_movement', 'sound_design')
    segment = _object({'duration': {'type': 'number', 'exclusiveMinimum': 0, 'maximum': duration_range[1]},
        'description': _STRING, 'shot_size_and_camera': _STRING, 'visual_prose': _STRING,
        'actions': _STRINGS, 'camera_movement': _STRING})
    shot = _object({'duration': duration, **{key: _STRING for key in text_fields},
        'transition': {**_STRING, 'description': '本段收尾画面或声音、具体剪辑点与下一段的承接；末段写收束。'},
        'effect_restrictions': _STRINGS, 'allowed_effects': _STRINGS,
        'visible_asset_names': {**_STRINGS, 'description': '本镜引用的全部角色、场景和道具，包含发声角色；名单不强制角色出现在画面中。'},
        'actions': _array(action), 'dialogue': _array(speech), 'narration': _array(speech),
        'source_scene_number': {'type': ['string', 'null']},
        'duration_split_part': {'type': ['integer', 'null'], 'minimum': 2},
        'segments': {**_array(segment), 'description': '同一次生成内的机位序列。观看重点改变并切机位时，依次写全各机位与切点动机，秒数合计为本段时长；连续单机位留空。'},
        'blocking_map': blocking if blocking_maps else {'type': 'null'}})
    return _object({'shots': {'type': 'array', 'items': shot, 'minItems': 1, 'maxItems': 200}})


CONTRACTS = {
    'story': _object({
        'book_types': _STRINGS,
        'story_outline': _STRING,
        'key_characters': {'type': 'array', 'items': _object({
            'name': _STRING, 'aliases': _STRINGS, 'role': _STRING, 'description': _STRING,
            'chapter_numbers': {'type': 'array', 'items': {'type': 'integer'}},
        })},
    }),
    'screenplay': _object({'screenplay': _STRING}),
}


def output_contract(task: str, *, asset_specifications=None, duration_range=(1, 30), blocking_maps=False) -> dict:
    schema = (asset_contract(asset_specifications) if task == 'assets' else
              storyboard_contract(duration_range, blocking_maps) if task == 'storyboard' else CONTRACTS[task])
    return {'name': task, 'version': 1, 'schema': deepcopy(schema)}


def bind_storyboard_candidates(contract: dict, entities: list[dict]) -> dict:
    """Use the actual request context as the sole source of allowed references."""
    result = deepcopy(contract)
    names = list(dict.fromkeys(entity['name'] for entity in entities))
    speakers = list(dict.fromkeys([entity['name'] for entity in entities if entity['asset_type'] == '人物'] + ['旁白', 'Narrator']))
    fields = result['schema']['properties']['shots']['items']['properties']
    fields['visible_asset_names'] = ({'type': 'array', 'items': {'type': 'string', 'enum': names}}
                                     if names else {'type': 'array', 'items': {'type': 'string'}, 'maxItems': 0})
    for key in ('dialogue', 'narration'):
        fields[key]['items']['properties']['speaker'] = {'type': 'string', 'enum': speakers}
    if fields['blocking_map'].get('type') == 'object':
        fields['blocking_map']['properties']['assets']['items']['properties']['asset_name'] = (
            {'type': ['string', 'null'], 'enum': [*names, None]} if names else {'type': 'null'})
    return result


def scene_prompt_edit_contract():
    return {'name': 'scene_prompt_edit', 'schema': _object({'prompt': {
        'type': 'string', 'minLength': 1,
        'description': '修改后的完整分镜提示词，包含未修改的内容。',
    }})}


def scene_prompt_batch_contract(scene_ids):
    return {'name': 'scene_prompt_edit', 'schema': _object({
        'prompts': _object({str(identifier): _nullable({
            'type': 'string', 'minLength': 1,
            'description': '修改后的完整提示词；无需修改时返回 null。',
        }) for identifier in scene_ids}),
        'reply': {'type': 'string', 'description': '简短说明修改内容或回答问题，不使用 Markdown。'},
    })}
