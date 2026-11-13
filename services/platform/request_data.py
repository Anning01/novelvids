"""Only bounded JSON metadata crosses the public generation API."""
import json

from fastapi import HTTPException, Request
from pydantic import ValidationError

MAX_REQUEST_BYTES = 1024 * 1024


def reject_inline_media(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"b64_json", "file_data"} or key == "input_audio" and isinstance(child, dict) and "data" in child:
                raise HTTPException(422, "Upload media directly to temporary OSS and send its read_url")
            reject_inline_media(child)
    elif isinstance(value, list):
        for child in value:
            reject_inline_media(child)
    elif isinstance(value, str) and value.lstrip().lower().startswith("data:"):
        raise HTTPException(422, "Inline media is not accepted; use temporary OSS URLs")


async def bounded_json_body(request: Request):
    if request.method not in {"POST", "PUT", "PATCH"}:
        return
    if request.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
        raise HTTPException(400, "Send JSON with media URLs; request a direct upload at /v1/media/uploads")
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > MAX_REQUEST_BYTES:
        raise HTTPException(413, "JSON request exceeds 1 MB; upload media directly to temporary OSS")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_REQUEST_BYTES:
            raise HTTPException(413, "JSON request exceeds 1 MB; upload media directly to temporary OSS")
        body.extend(chunk)
    request._body = bytes(body)
    try:
        data = json.loads(body)
    except ValueError:
        raise HTTPException(400, "Request body must be valid JSON") from None
    reject_inline_media(data)


def validated_body(schema, values):
    try:
        return schema.model_validate(values)
    except ValidationError as error:
        detail = error.errors()[0]
        field = ".".join(str(value) for value in detail["loc"])
        raise HTTPException(422, f"{field}: {detail['msg']}") from None


def sdk_request_schema(model):
    schema = model.model_json_schema()
    definitions = schema.pop("$defs", {})
    def inline(value):
        if isinstance(value, dict):
            if "$ref" in value:
                return inline(definitions[value["$ref"].rsplit("/", 1)[1]])
            return {key:inline(item) for key,item in value.items()}
        if isinstance(value, list):
            return [inline(item) for item in value]
        return value
    return {"requestBody":{"required":True, "content":{"application/json":{"schema":inline(schema)}}}}
