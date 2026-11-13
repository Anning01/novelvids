"""Public, credential-free integration instructions rendered for the current host."""
from pathlib import Path

GUIDE = Path(__file__).resolve().parents[2] / "prompts" / "platform_api_agent.md"


def agent_guide(base_url: str) -> str:
    return GUIDE.read_text(encoding="utf-8").replace("{{BASE_URL}}", base_url.rstrip("/"))
