from models.audio_reference import AudioReference
from models.digital_human import DigitalHuman
from schemas.media_library import AudioReferenceOut, DigitalHumanOut
from utils.crud import CRUDBase


class AudioReferenceController(CRUDBase):
    def __init__(self):
        super().__init__(model=AudioReference)


class DigitalHumanController(CRUDBase):
    def __init__(self):
        super().__init__(model=DigitalHuman)


audio_reference_controller = AudioReferenceController()
digital_human_controller = DigitalHumanController()

AUDIO_SEARCH_FIELDS = ["nickname", "gender", "asset_id"]
DIGITAL_HUMAN_SEARCH_FIELDS = ["country", "gender", "occupation", "asset_id"]

__all__ = [
    "AUDIO_SEARCH_FIELDS",
    "DIGITAL_HUMAN_SEARCH_FIELDS",
    "AudioReferenceOut",
    "DigitalHumanOut",
    "audio_reference_controller",
    "digital_human_controller",
]
