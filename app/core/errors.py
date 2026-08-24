from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class AppError(Exception):
    code: str
    message: str
    http_status: int = 500
    retryable: bool = False
    errors: list[dict[str, Any]] = field(default_factory=list)

    def __str__(self) -> str:
        return self.message


AMAP_ERROR_MAP: dict[str, tuple[str, str, int, bool]] = {
    "10001": ("AMAP_AUTH_FAILED", "高德 Key 不正确或已过期", 502, False),
    "10002": ("AMAP_AUTH_FAILED", "高德 Key 没有所请求服务的权限", 502, False),
    "10003": ("AMAP_QUOTA_EXCEEDED", "高德日调用量已超限", 503, True),
    "10004": ("AMAP_RATE_LIMITED", "高德接口访问过于频繁", 503, True),
    "10005": ("AMAP_AUTH_FAILED", "服务器出口 IP 不在高德 Key 白名单", 502, False),
    "10009": ("AMAP_AUTH_FAILED", "高德 Key 平台类型不匹配，应使用 Web 服务 Key", 502, False),
    "10016": ("PROVIDER_UNAVAILABLE", "高德服务繁忙", 503, True),
    "20000": ("PROVIDER_INVALID_REQUEST", "高德请求参数非法", 422, False),
    "20001": ("PROVIDER_INVALID_REQUEST", "高德请求缺少必填参数", 422, False),
    "20801": ("ROUTE_NOT_FOUND", "起终点附近没有可用道路", 404, False),
    "20802": ("ROUTE_NOT_FOUND", "高德无法计算该路线", 404, False),
    "20803": ("ROUTE_NOT_FOUND", "路线超出高德支持范围", 404, False),
}


def error_from_amap(infocode: str, info: str) -> AppError:
    code, message, status, retryable = AMAP_ERROR_MAP.get(
        infocode,
        ("PROVIDER_UNAVAILABLE", f"高德服务返回错误：{info or infocode}", 502, True),
    )
    return AppError(code, message, status, retryable)
