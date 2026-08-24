import pytest

from app.core.errors import AppError, error_from_amap
from app.infrastructure.amap import AmapClient


@pytest.mark.asyncio
async def test_missing_key_fails_before_any_provider_request() -> None:
    client = AmapClient(
        api_key=None,
        base_url="https://restapi.amap.com",
        timeout_seconds=8,
    )
    try:
        with pytest.raises(AppError) as captured:
            await client.resolve_city("北京市")
        assert captured.value.code == "AMAP_KEY_MISSING"
        assert captured.value.retryable is False
    finally:
        await client.close()


def test_platform_mismatch_has_actionable_error() -> None:
    error = error_from_amap("10009", "USERKEY_PLAT_NOMATCH")

    assert error.code == "AMAP_AUTH_FAILED"
    assert "Web 服务 Key" in error.message
    assert error.http_status == 502
