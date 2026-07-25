from pydantic import BaseModel


class WorkbenchCapabilitiesOut(BaseModel):
    """创作画布在当前部署中可执行的真实能力。"""

    upload_media: bool = True
    generate_asset: bool = True
    generate_video: bool = True
    apply_watermark: bool = False
    compose_video: bool = False
