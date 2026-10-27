from pydantic import ValidationError
import pytest

from schemas.creation_agent import AgentConfiguration, LEGACY_AGENT_DEFAULTS, stored_agent_configuration


def test_creation_agent_defaults_use_deepseek_long_context_envelope():
    configuration = AgentConfiguration()

    assert configuration.request_limit == 20
    assert configuration.tool_calls_limit == 50
    assert configuration.max_targets == 32
    assert configuration.timeout_seconds == 600
    assert configuration.working_input_tokens == 840_000
    assert configuration.max_context_characters is None
    assert configuration.context_page_characters == 4_000
    assert configuration.max_output_tokens == 64_000
    assert configuration.total_tokens_limit == 2_000_000
    assert configuration.compaction_trigger_ratio == 0.70
    assert configuration.compaction_target_ratio == 0.45


def test_creation_agent_accepts_deepseek_published_output_maximum():
    configuration = AgentConfiguration(max_output_tokens=384_000)

    assert configuration.max_output_tokens == 384_000
    with pytest.raises(ValidationError):
        AgentConfiguration(max_output_tokens=384_001)


def test_untouched_legacy_defaults_upgrade_without_overwriting_custom_profiles():
    upgraded = stored_agent_configuration({'enabled': True, **LEGACY_AGENT_DEFAULTS})
    custom = stored_agent_configuration({'enabled': True, **LEGACY_AGENT_DEFAULTS, 'request_limit': 9})

    assert upgraded.enabled is True
    assert upgraded.working_input_tokens == 840_000
    assert upgraded.max_output_tokens == 64_000
    assert custom.request_limit == 9
    assert custom.working_input_tokens == 12_000


def test_sparse_legacy_defaults_do_not_keep_an_obsolete_character_cap():
    configuration = stored_agent_configuration({
        'enabled': True, 'request_limit': 6, 'tool_calls_limit': 8,
        'max_targets': 8, 'timeout_seconds': 180,
        'max_context_characters': 64000, 'history_runs': 6,
        'max_output_tokens': 8000, 'total_tokens_limit': 100000,
    })
    assert configuration.max_context_characters is None
    assert configuration.enabled
    assert configuration.working_input_tokens == 840000


def test_optional_character_cap_preserves_explicit_admin_values():
    assert AgentConfiguration().max_context_characters is None
    assert AgentConfiguration(max_context_characters=None).max_context_characters is None
    assert AgentConfiguration(max_context_characters=64000).max_context_characters == 64000
    assert stored_agent_configuration({'request_limit': 9, **{key: value for key, value in LEGACY_AGENT_DEFAULTS.items() if key != 'request_limit'}}).max_context_characters == 64000


@pytest.mark.parametrize('assistant_limit,model_limit,expected', [
    (None, None, None), (None, 64000, 64000), (100000, None, 100000),
    (100000, 64000, 64000), (64000, 100000, 64000),
])
def test_only_explicit_model_or_assistant_character_caps_apply(assistant_limit, model_limit, expected):
    assert AgentConfiguration(max_context_characters=assistant_limit).context_character_limit(model_limit) == expected
