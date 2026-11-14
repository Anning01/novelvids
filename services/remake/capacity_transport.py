"""Wait for platform admission without replaying requests already accepted."""
import asyncio

import httpx

from services.image_generation.gateway import _capacity_retry_delay


class PlatformCapacityTransport(httpx.AsyncHTTPTransport):
    async def handle_async_request(self, request):
        while True:
            response = await super().handle_async_request(request)
            if response.status_code != 429:
                return response
            await response.aread()
            delay = _capacity_retry_delay(response)
            if delay is None:
                return response
            await response.aclose()
            from services.billing.platform import active_model_call
            active = active_model_call.get()
            if active:
                active[1].update(rate_limit_reason="model_concurrency", retry_after_seconds=delay,
                                 admission_retry_count=active[1].get("admission_retry_count", 0) + 1)
            await asyncio.sleep(delay)
