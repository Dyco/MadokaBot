"""HLTV 页面抓取客户端。"""

from __future__ import annotations

import asyncio
import calendar
from datetime import datetime, timezone
from urllib.parse import urlencode, urljoin, urlparse

import httpx
from nonebot.log import logger

from ..madoka_bundle.config import config as madoka_config
from .config import config
from .models import EventData, EventMatchRef, MatchData
from .parser import (
    parse_event_html,
    parse_event_match_refs_html,
    parse_events_html,
    parse_match_html,
)


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


def match_id_from_url(value: str) -> str | None:
    """从 HLTV 比赛链接中提取比赛 ID。"""
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"}:
        return None

    hostname = (parsed.hostname or "").casefold()
    configured_hostname = (
        urlparse(str(config.hltv_base_url)).hostname or "www.hltv.org"
    ).casefold()
    if hostname not in {configured_hostname, "hltv.org", "www.hltv.org"}:
        return None

    path_parts = [part for part in parsed.path.split("/") if part]
    if len(path_parts) < 2 or path_parts[0].casefold() != "matches":
        return None
    match_id = path_parts[1]
    return match_id if match_id.isdigit() else None


def event_url(event_id: str, section: str | None = None) -> str:
    """生成赛事详情或赛事比赛列表地址。"""
    suffix = f"/{section}" if section else ""
    return urljoin(
        str(config.hltv_base_url).rstrip("/") + "/",
        f"events/{event_id}{suffix}",
    )


def events_url() -> str:
    """生成同时筛选 Major 和 International LAN 的 HLTV 赛事列表地址。"""
    base_url = urljoin(str(config.hltv_base_url).rstrip("/") + "/", "events")
    query = urlencode(
        [("eventType", "MAJOR"), ("eventType", "INTLLAN")],
    )
    return f"{base_url}?{query}"


def _add_months(value: datetime, months: int) -> datetime:
    """将日期推进指定月数，并处理目标月份没有当天日期的情况。"""
    month_index = value.year * 12 + value.month - 1 + months
    year, month_index = divmod(month_index, 12)
    month = month_index + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def _request_headers() -> dict[str, str]:
    """生成 HLTV 页面请求头。"""
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": str(config.hltv_base_url).rstrip("/") + "/",
    }


async def _fetch_html(page_url: str) -> tuple[str, str]:
    """请求 HLTV 页面并返回正文与最终地址。"""
    try:
        async with httpx.AsyncClient(
            proxy=_proxy(),
            trust_env=False,
            follow_redirects=True,
            headers=_request_headers(),
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
    return response.text, str(response.url)


def filter_events(
    events: list[EventData],
    *,
    now: datetime | None = None,
) -> list[EventData]:
    """筛选当前进行中和未来三个月内符合条件的赛事。"""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    # 以月份为边界，当前月加未来三个月都纳入查询范围。
    deadline_month = _add_months(current.replace(day=1), 3)
    deadline = deadline_month.replace(
        day=calendar.monthrange(deadline_month.year, deadline_month.month)[1],
        hour=23,
        minute=59,
        second=59,
        microsecond=999999,
    )
    selected: list[EventData] = []
    for event in events:
        if event.start_at is None:
            continue
        ongoing = event.start_at <= current and (
            event.end_at is None or event.end_at >= current
        )
        upcoming = current <= event.start_at <= deadline
        if not (ongoing or upcoming):
            continue

        event_type = event.event_type.casefold()
        is_major = event_type == "major" or "major" in event.name.casefold()
        is_intl_lan = event_type in {"intl. lan", "international lan"}
        if is_major or (is_intl_lan and (event.prize_pool or 0) >= 200_000):
            selected.append(event)

    return sorted(
        selected,
        key=lambda event: event.start_at or datetime.max.replace(tzinfo=timezone.utc),
    )


async def fetch_events() -> list[EventData]:
    """获取并筛选 HLTV 当前和未来三个月的重点赛事。"""
    page_url = events_url()
    html, response_url = await _fetch_html(page_url)
    return filter_events(
        parse_events_html(html, page_url=response_url)
    )


async def fetch_event(event_id: str) -> EventData:
    """抓取并解析赛事详情。"""
    normalized_id = str(event_id).strip()
    if not normalized_id.isdigit():
        raise HltvError("赛事 ID 必须是纯数字。")

    page_html, response_url = await _fetch_html(event_url(normalized_id))
    event = parse_event_html(
        page_html,
        event_id=normalized_id,
        page_url=response_url,
    )
    if event is None:
        raise HltvError("没有从 HLTV 页面解析到赛事信息，可能是页面结构发生变化。")
    return event


async def fetch_event_match_refs(event_id: str) -> list[EventMatchRef]:
    """获取赛事的待进行比赛和历史结果链接。"""
    normalized_id = str(event_id).strip()
    if not normalized_id.isdigit():
        raise HltvError("赛事 ID 必须是纯数字。")

    pages = await asyncio.gather(
        _fetch_html(event_url(normalized_id, "matches")),
        _fetch_html(event_url(normalized_id, "results")),
        return_exceptions=True,
    )
    refs: dict[str, EventMatchRef] = {}
    errors: list[BaseException] = []
    for section, page in zip(("upcoming", "result"), pages):
        if isinstance(page, BaseException):
            errors.append(page)
            continue
        html, response_url = page
        for ref in parse_event_match_refs_html(
            html,
            page_url=response_url,
            section=section,
        ):
            previous = refs.get(ref.match_id)
            if previous is None or section == "upcoming":
                refs[ref.match_id] = ref
    if not refs and errors:
        error = errors[0]
        if isinstance(error, HltvError):
            raise error
        raise HltvError("HLTV 赛事比赛列表请求失败。") from error
    return list(refs.values())


async def fetch_match(match_id: str) -> MatchData:
    """抓取并解析一场赛事。"""
    normalized_id = str(match_id).strip()
    if not normalized_id.isdigit():
        raise HltvError("赛事 ID 必须是纯数字。")

    page_url = match_url(normalized_id)
    html, response_url = await _fetch_html(page_url)
    match = parse_match_html(
        html,
        match_id=normalized_id,
        page_url=response_url,
    )
    if not match.teams:
        logger.warning("HLTV 页面未找到赛事队伍：%s", response_url)
        raise HltvError("没有从 HLTV 页面解析到赛事信息，可能是页面结构发生变化。")
    return match

