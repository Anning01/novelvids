"""Story and cover instructions share the Chinese skill pack."""

from prompts.skill_pack import render_skill, task_facts


def render_analysis_messages(*, name, chapter_count, material, prompt_language):
    return [
        {"role": "system", "content": render_skill("story", prompt_language)},
        {"role": "user", "content": task_facts({
            "name": name, "chapter_count": chapter_count, "manuscript": material,
        })},
    ]


def render_cover_prompt(*, name, book_types, story_outline, prompt_language="en"):
    return render_skill("image", prompt_language) + "\n" + task_facts({
        "purpose": "project_cover", "name": name, "genres": book_types,
        "outline": story_outline, "aspect_ratio": "2:3",
    })
