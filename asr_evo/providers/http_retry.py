from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx

T = TypeVar("T", bound=httpx.Response)

RETRY_STATUS_CODES = {429, 502, 503, 504}


async def with_http_retries(
    request: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    base_delay: float = 0.5,
) -> T:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            response = await request()
            if response.status_code not in RETRY_STATUS_CODES or attempt == attempts - 1:
                return response
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            last_error = exc
            if attempt == attempts - 1:
                raise ProviderHTTPError("Network error while calling provider") from exc
        await asyncio.sleep(base_delay * (2**attempt))
    if last_error:
        raise ProviderHTTPError("Network error while calling provider") from last_error
    raise ProviderHTTPError("Provider request failed after retries")


class ProviderHTTPError(RuntimeError):
    pass


def raise_provider_status(response: httpx.Response) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = _compact_error_body(response)
        raise ProviderHTTPError(
            f"Provider HTTP {response.status_code}: {detail}"
        ) from exc


def _compact_error_body(response: httpx.Response) -> str:
    text = response.text.strip().replace("\n", " ")
    if not text:
        return response.reason_phrase
    return text[:300]
