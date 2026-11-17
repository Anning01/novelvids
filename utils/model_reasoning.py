"""Render explicit model preferences without guessing provider capabilities."""


def reasoning_parameters(thinking=None, reasoning_effort=None, *, text_api="chat_completions") -> dict:
    result = {}
    if thinking:
        result['thinking'] = {'type': thinking} if thinking in ('enabled', 'disabled') else thinking
    if reasoning_effort:
        result['reasoning_effort'] = reasoning_effort
    if text_api == "responses":
        effort = result.pop('reasoning_effort', None)
        if thinking == 'disabled':
            effort = 'none'
        if thinking in ('enabled', 'disabled'):
            result.pop('thinking', None)
        if effort is not None:
            result['reasoning'] = {'effort': effort}
    return result
