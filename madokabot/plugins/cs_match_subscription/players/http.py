"""平台请求客户端、重试和异常转换。"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from nonebot.log import logger

from madokabot.core.config import config as madoka_config

from ..config import config
from ..net import resolve_proxy
from .models import PlayerStatsError


def create_client() -> httpx.AsyncClient:
    """创建平台接口共用的 HTTP 客户端。"""
    return httpx.AsyncClient(
        proxy=resolve_proxy(config.hltv_proxy, madoka_config.proxy),
        trust_env=False,
        follow_redirects=True,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
            )
        },
        timeout=httpx.Timeout(config.hltv_request_timeout, connect=10.0),
    )


async def request_json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    retry_attempts: int = 0,
    retry_delay: float = 0.5,
    **kwargs: Any,
) -> dict[str, Any]:
    """请求 JSON 接口，按配置重试临时错误并统一转换为业务异常。"""
    attempts = max(0, int(retry_attempts))
    retryable_statuses = {408, 425, 429, 500, 502, 503, 504}

    for attempt in range(attempts + 1):
        try:
            response = await client.request(method, url, **kwargs)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status not in retryable_statuses or attempt >= attempts:
                suffix = (
                    f"，已重试 {attempts} 次" if status in retryable_statuses else ""
                )
                raise PlayerStatsError(
                    f"平台接口返回 HTTP {status}{suffix}（{method} {url}）"
                ) from exc
            logger.warning(
                "平台接口 %s %s 返回 HTTP %s，将在第 %s/%s 次重试",
                method,
                url,
                status,
                attempt + 1,
                attempts,
            )
        except (httpx.HTTPError, ValueError) as exc:
            if attempt >= attempts:
                detail = str(exc).strip() or repr(exc) or type(exc).__name__
                suffix = f"，已重试 {attempts} 次" if attempts else ""
                raise PlayerStatsError(
                    f"平台接口请求失败{suffix}（{method} {url}，"
                    f"{type(exc).__name__}）：{detail}"
                ) from exc
            logger.warning(
                "平台接口 %s %s 请求异常（%s：%s），将在第 %s/%s 次重试",
                method,
                url,
                type(exc).__name__,
                str(exc).strip() or repr(exc),
                attempt + 1,
                attempts,
            )
        else:
            if not isinstance(payload, dict):
                raise PlayerStatsError("平台接口返回格式异常")
            return payload

        await asyncio.sleep(max(0.0, retry_delay) * (attempt + 1))

    raise PlayerStatsError(f"平台接口请求失败（{method} {url}）")
