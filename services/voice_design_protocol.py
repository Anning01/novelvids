"""OpenAI-style non-streaming voice design with a WAV payload."""

import base64
from dataclasses import dataclass
from io import BytesIO
import wave

import httpx
from fastapi import HTTPException
from schemas.voice_design import VoiceDesignRequest

from services.audio_references import MAX_AUDIO_BYTES
from utils.messages import localized_message as msg


VOICE_PROTOCOLS = {"mimo_voice_design", "openai_compatible", "novelvids"}


@dataclass(frozen=True)
class VoiceSample:
    data: bytes
    seconds: float
    response: dict


async def synthesize_voice(client: httpx.AsyncClient, config, request: VoiceDesignRequest) -> VoiceSample:
    header = {"api-key": config.api_key} if config.api_protocol == "mimo_voice_design" else {
        "Authorization": f"Bearer {config.api_key}"}
    payload = request.model_dump(mode="json")
    payload["model"] = config.model
    response = await client.post(config.base_url.rstrip("/") + "/chat/completions", headers=header, json=payload)
    response.raise_for_status()
    try:
        body = response.json()
        encoded = body["choices"][0]["message"]["audio"]["data"]
        if not isinstance(encoded, str) or len(encoded) > ((MAX_AUDIO_BYTES + 2) // 3) * 4:
            raise ValueError("Invalid WAV size")
        data = base64.b64decode(encoded, validate=True)
        with wave.open(BytesIO(data), "rb") as audio:
            frames = audio.getnframes()
            size = frames * audio.getsampwidth() * audio.getnchannels()
            if not frames or len(audio.readframes(frames)) != size or len(data) > MAX_AUDIO_BYTES:
                raise ValueError("Invalid WAV data")
            seconds = frames / audio.getframerate()
    except (KeyError, IndexError, TypeError, ValueError, wave.Error, EOFError):
        raise HTTPException(502, msg("音色模型返回了无效的 WAV 音频")) from None
    return VoiceSample(data, seconds, body)
