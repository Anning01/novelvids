from enum import StrEnum


class ImageApiProtocol(StrEnum):
    """Supported image-generation wire protocols."""

    openai_compatible = "openai_compatible"
    openrouter_compatible = "openrouter_compatible"
    volcengine_ark = "volcengine_ark"
    minimax = "minimax"
