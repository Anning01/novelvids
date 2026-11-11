"""Explicit animation requirements for GIF image output."""

from utils.prompt_language import normalize_prompt_language


def render_gif_prompt(prompt: str, *, frame_count: int, frame_duration_ms: int, language: str) -> str:
    requirement = (
        f"生成 {frame_count} 帧 GIF 动图，每帧间隔 {frame_duration_ms} 毫秒：将上述描述中的动作表现为连续运动，首尾无缝衔接并循环播放。不要输出静态图片。"
        if normalize_prompt_language(language) == "zh" else
        f"Generate an animated GIF with {frame_count} frames and a delay of {frame_duration_ms} milliseconds per frame. Show the described actions as continuous motion, with a seamless loop connecting the last frame to the first. Do not output a still image."
    )
    return f"{prompt}\n\n{requirement}"
