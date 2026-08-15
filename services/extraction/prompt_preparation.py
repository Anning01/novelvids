"""Prepare model-produced visual traits as editable database prompts."""

from prompts.reference import render_default_asset_prompt
from services.extraction.extractor import AssetExtractionResult


class AssetPromptPreparationService:
    """Convert extraction output into complete prompts before persistence."""

    def prepare(
        self,
        result: AssetExtractionResult,
        *,
        prompt_language: str,
    ) -> AssetExtractionResult:
        persons = [
            person.model_copy(update={
                "base_traits": render_default_asset_prompt(
                    asset_type="person",
                    visual_traits=person.base_traits,
                    prompt_language=prompt_language,
                    reference_layout=person.reference_layout,
                ),
            })
            for person in result.persons
        ]
        scenes = [
            scene.model_copy(update={
                "base_traits": render_default_asset_prompt(
                    asset_type="scene",
                    visual_traits=scene.base_traits,
                    prompt_language=prompt_language,
                ),
            })
            for scene in result.scenes
        ]
        items = [
            item.model_copy(update={
                "base_traits": render_default_asset_prompt(
                    asset_type="item",
                    visual_traits=item.base_traits,
                    prompt_language=prompt_language,
                ),
            })
            for item in result.items
        ]
        return result.model_copy(update={
            "persons": persons,
            "scenes": scenes,
            "items": items,
        })
