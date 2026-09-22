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
    assert configuration.max_context_characters == 2_000_000
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
