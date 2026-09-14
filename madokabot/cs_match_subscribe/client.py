"""HLTV 页面抓取客户端。"""

from __future__ import annotations

from urllib.parse import urljoin

import httpx
from nonebot.log import logger

from ..madoka_bundle.config import config as madoka_config
from .config import config
from .models import MatchData
from .parser import parse_match_html


class HltvError(RuntimeError):
    """HLTV 页面不可用或无法解析。"""


def _proxy() -> str | None:
    proxy = config.hltv_proxy or madoka_config.proxy
    if proxy is None:
        return None
    value = str(proxy).strip()
    if not value:
        return None
    return value if "://" in value else f"http://{value}"


def match_url(match_id: str) -> str:
    """生成只依赖赛事 ID 的 HLTV 页面地址。"""
    return urljoin(str(config.hltv_base_url).rstrip("/") + "/", f"matches/{match_id}")


async def fetch_match(match_id: str) -> MatchData:
    """抓取并解析一场赛事。"""
    normalized_id = str(match_id).strip()
    if not normalized_id.isdigit():
        raise HltvError("赛事 ID 必须是纯数字。")

    page_url = match_url(normalized_id)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": str(config.hltv_base_url).rstrip("/") + "/",
    }
    try:
        async with httpx.AsyncClient(
            proxy=_proxy(),
            trust_env=False,
            follow_redirects=True,
            headers=headers,
            timeout=httpx.Timeout(config.hltv_request_timeout, connect=10.0),
        ) as client:
            response = await client.get(page_url)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in {403, 429}:
            raise HltvError(
                f"HLTV 暂时拒绝访问（HTTP {exc.response.status_code}），请检查代理或稍后重试。"
            ) from exc
        raise HltvError(f"HLTV 请求失败（HTTP {exc.response.status_code}）。") from exc
    except httpx.HTTPError as exc:
        raise HltvError(f"HLTV 网络请求失败：{exc}") from exc

    match = parse_match_html(
        response.text,
        match_id=normalized_id,
        page_url=str(response.url),
    )
    if not match.teams:
        logger.warning("HLTV 页面未找到赛事队伍：%s", response.url)
        raise HltvError("没有从 HLTV 页面解析到赛事信息，可能是页面结构发生变化。")
    return match

