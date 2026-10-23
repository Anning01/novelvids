"""视频展示名称与实际文件名分离，保留文件格式元数据。"""
import re


def video_display_name(value: str) -> str:
    return re.sub(r"\.(?:mp4|mov)$", "", value.strip(), flags=re.IGNORECASE).strip() or "video"
