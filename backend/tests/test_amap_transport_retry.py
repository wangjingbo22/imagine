from __future__ import annotations

import httpx
import pytest

from app.core.errors import AppError
from app.infrastructure.amap import AmapClient


@pytest.mark.asyncio
async def test_retries_temporary_connection_failure() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise httpx.ConnectError("temporary proxy failure", request=request)
        return httpx.Response(
            200,
            json={"status": "1", "infocode": "10000", "pois": []},
        )

    client = AmapClient(
        api_key="test-key",
        base_url="https://restapi.amap.com",
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
        retry_attempts=3,
        retry_backoff_seconds=0,
    )
    try:
        payload = await client.search_places(
            city_code="310000",
            keywords="景点",
            types=[],
            page=1,
            page_size=20,
        )
    finally:
        await client.close()

    assert payload["status"] == "1"
    assert attempts == 3


@pytest.mark.asyncio
async def test_does_not_retry_authentication_failure() -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            200,
            json={"status": "0", "infocode": "10001", "info": "INVALID_USER_KEY"},
        )

    client = AmapClient(
        api_key="bad-key",
        base_url="https://restapi.amap.com",
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
        retry_attempts=3,
        retry_backoff_seconds=0,
    )
    try:
        with pytest.raises(AppError) as captured:
            await client.resolve_city("上海")
    finally:
        await client.close()

    assert captured.value.code == "AMAP_AUTH_FAILED"
    assert attempts == 1
