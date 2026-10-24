"""Optional HTTP idempotency envelope; existing clients remain compatible."""

import hashlib
from uuid import UUID
from fastapi import Header, Request
from services.creation_agent.submissions import submission


async def production_request(
    request: Request, x_creation_request_id: UUID | None = Header(None)
):
    value = None
    if x_creation_request_id:
        digest = hashlib.sha256(
            request.method.encode()
            + str(request.url.path).encode()
            + request.url.query.encode()
            + await request.body()
        ).hexdigest()
        value = {"submission_id": str(x_creation_request_id), "submission_hash": digest}
    token = submission.set(value)
    try:
        yield
    finally:
        submission.reset(token)
