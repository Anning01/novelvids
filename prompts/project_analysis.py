"""Story and cover instructions share the Chinese skill pack."""

from prompts.skill_pack import render_skill, task_facts




def render_cover_prompt(*, name, book_types, story_outline, prompt_language="en", aspect_ratio="2:3"):
    return render_skill("image", prompt_language) + "\n" + task_facts({
        "purpose": "project_cover", "name": name, "genres": book_types,
        "outline": story_outline, "aspect_ratio": aspect_ratio,
    })
