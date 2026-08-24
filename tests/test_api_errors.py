import httpx
import pytest

from app.main import create_app


class UnusedService:
    pass


@pytest.mark.asyncio
async def test_docs_page_uses_chinese_interface() -> None:
    app = create_app(service=UnusedService())  # type: ignore[arg-type]
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/docs")

    assert response.status_code == 200
    assert 'lang="zh-CN"' in response.text
    assert "试一试" in response.text
    assert "数据模型" in response.text
    assert "行知旅伴接口文档" in response.text


@pytest.mark.asyncio
async def test_validation_error_matches_confirmed_contract() -> None:
    app = create_app(service=UnusedService())  # type: ignore[arg-type]
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/places/search",
            json={
                "schemaVersion": "1.0",
                "tripId": "not-a-uuid",
                "cityContext": {
                    "countryCode": "CN",
                    "cityCode": "110000",
                    "cityName": "北京市",
                    "center": {"longitude": 116.4},
                    "providerConfig": {"provider": "AMAP", "coordinateSystem": "GCJ02"},
                },
                "keywords": "公园",
            },
        )

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "TRIP_SCHEMA_INVALID"
    assert body["schemaVersion"] == "1.0"
    assert set(body) == {"code", "schemaVersion", "errors"}
    paths = {item["path"] for item in body["errors"]}
    assert "tripId" in paths
    assert "cityContext.center.latitude" in paths
