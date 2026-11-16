"""Render explicit model preferences without guessing provider capabilities."""


def reasoning_parameters(thinking=None, reasoning_effort=None) -> dict:
    result = {}
    if thinking:
        result['thinking'] = {'type': thinking} if thinking in ('enabled', 'disabled') else thinking
    if reasoning_effort:
        result['reasoning_effort'] = reasoning_effort
    return result
