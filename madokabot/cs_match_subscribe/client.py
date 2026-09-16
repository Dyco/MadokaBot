"""HLTV 页面抓取客户端。"""

from __future__ import annotations

import asyncio
import calendar
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlencode, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from nonebot.log import logger

from ..madoka_bundle.config import config as madoka_config
from .config import config
from .models import EventData, EventMatchRef, MatchData
from .net import resolve_proxy
from .parser import (
    parse_event_html,
    parse_event_match_refs_html,
    parse_events_html,
    parse_match_html,
)


class HltvError(RuntimeError):
    """HLTV 页面不可用或无法解析。"""


@dataclass(frozen=True, slots=True)
class FlaresolverrSession:
    """FlareSolverr 返回的浏览器会话信息，供资源浏览器复用。"""

    user_agent: str = ""
    cookies: tuple[dict[str, object], ...] = ()


_FLARESOLVERR_SEMAPHORE = asyncio.Semaphore(1)
_FLARESOLVERR_SESSION: FlaresolverrSession | None = None
_CHALLENGE_MARKERS = (
    "checking your browser",
    "verify you are human",
    "enable javascript and cookies",
    "performing security verification",
)
_CHALLENGE_TITLE_MARKERS = (
    "just a moment",
    "checking your browser",
    "verify you are human",
)
_CHALLENGE_SELECTORS = (
    "#challenge-stage",
    "#challenge-error-text",
    "#cf-chl-widget",
    ".cf-chl-widget",
    "form#challenge-form",
    "[name='cf-turnstile-response']",
    "iframe[src*='challenges.cloudflare.com']",
)


def _flaresolverr_url() -> str:
    """返回 FlareSolverr 的 v1 API 地址。"""
    value = str(config.hltv_flaresolverr_url).strip().rstrip("/")
    if not value:
        raise HltvError("未配置 FlareSolverr API 地址。")
    return value if value.casefold().endswith("/v1") else f"{value}/v1"


def _flaresolverr_proxy() -> dict[str, str] | None:
    """将插件代理配置转换为 FlareSolverr 的 proxy 参数。"""
    proxy = config.hltv_flaresolverr_proxy
    if proxy is None:
        proxy = resolve_proxy(config.hltv_proxy, madoka_config.proxy)
    if proxy is None:
        return None
    value = str(proxy).strip()
    if not value:
        return None
    if "://" not in value:
        value = f"http://{value}"
    return {"url": value}


def _is_challenge_html(html: str) -> bool:
    """识别 FlareSolverr 偶尔返回的未完成浏览器验证页。"""
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    title_text = " ".join(title.casefold().split())
    if any(marker in title_text for marker in _CHALLENGE_TITLE_MARKERS):
        return True
    if any(soup.select_one(selector) is not None for selector in _CHALLENGE_SELECTORS):
        return True

    # 正常 HLTV 比赛页可能在新闻、回放描述等正文中出现诸如
    # “just a moment”的普通短语，不能再对整篇正文做无条件匹配。
    body = soup.body.get_text(" ", strip=True) if soup.body else ""
    body_text = " ".join(body.casefold().split())
    return len(body_text) <= 4_000 and any(
        marker in body_text for marker in _CHALLENGE_MARKERS
    )


def get_flaresolverr_session() -> FlaresolverrSession | None:
    """返回最近一次成功页面请求的浏览器会话信息。"""
    return _FLARESOLVERR_SESSION


def _remember_flaresolverr_session(solution: dict[str, object]) -> None:
    """保存 FlareSolverr 会话，供 Playwright 下载页面内图片。"""
    global _FLARESOLVERR_SESSION

    user_agent = solution.get("userAgent")
    normalized_user_agent = str(user_agent).strip() if user_agent else ""
    raw_cookies = solution.get("cookies")
    cookies: list[dict[str, object]] = []
    if isinstance(raw_cookies, list):
        for raw_cookie in raw_cookies:
            if not isinstance(raw_cookie, dict):
                continue
            name = raw_cookie.get("name")
            if not isinstance(name, str) or not name:
                continue
            cookie: dict[str, object] = {
                "name": name,
                "value": str(raw_cookie.get("value") or ""),
            }
            for key in ("domain", "path"):
                value = raw_cookie.get(key)
                if isinstance(value, str) and value:
                    cookie[key] = value
            expires = raw_cookie.get("expires")
            if isinstance(expires, (int, float)) and not isinstance(expires, bool):
                if expires > 0:
                    cookie["expires"] = float(expires)
            for key in ("httpOnly", "secure"):
                value = raw_cookie.get(key)
                if isinstance(value, bool):
                    cookie[key] = value
            same_site = raw_cookie.get("sameSite")
            if isinstance(same_site, str):
                same_site_value = same_site.casefold()
                if same_site_value in {"strict", "lax", "none"}:
                    cookie["sameSite"] = same_site_value.capitalize()
            cookies.append(cookie)

    _FLARESOLVERR_SESSION = FlaresolverrSession(
        user_agent=normalized_user_agent,
        cookies=tuple(cookies),
    )


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


def event_results_url(event_id: str) -> str:
    """生成当前 HLTV 使用的赛事结果页地址。"""
    base_url = urljoin(str(config.hltv_base_url).rstrip("/") + "/", "results")
    return f"{base_url}?{urlencode({'event': event_id})}"


def _canonical_event_url(
    html: str,
    *,
    event_id: str,
    page_url: str,
) -> str | None:
    """从赛事子页面找到带 slug 的 canonical overview 地址。"""
    soup = BeautifulSoup(html, "html.parser")
    for anchor in soup.select(
        ".event-hub-top[href], .event-hub a[href], a[href*='/events/']"
    ):
        href = anchor.get("href")
        if not isinstance(href, str) or not href:
            continue
        absolute = urljoin(page_url, href)
        parts = [part for part in urlparse(absolute).path.split("/") if part]
        if len(parts) < 3 or parts[0].casefold() != "events":
            continue
        if parts[1] != str(event_id):
            continue
        if parts[2].casefold() in {"matches", "results", "stats"}:
            continue
        return absolute
    return None


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


async def _call_flaresolverr(
    payload: dict[str, object],
    *,
    timeout: httpx.Timeout,
) -> dict[str, object]:
    """调用一次 FlareSolverr API。"""
    async with _FLARESOLVERR_SEMAPHORE:
        try:
            async with httpx.AsyncClient(
                trust_env=False,
                follow_redirects=True,
                headers={"Content-Type": "application/json"},
                timeout=timeout,
            ) as client:
                response = await client.post(_flaresolverr_url(), json=payload)
                response.raise_for_status()
                result = response.json()
        except httpx.HTTPStatusError as exc:
            raise HltvError(
                f"FlareSolverr API 请求失败（HTTP {exc.response.status_code}）。"
            ) from exc
        except httpx.HTTPError as exc:
            raise HltvError(f"无法连接 FlareSolverr：{exc}") from exc
        except ValueError as exc:
            raise HltvError("FlareSolverr 返回了无效的 JSON。") from exc

    if not isinstance(result, dict):
        raise HltvError("FlareSolverr 返回格式无效。")
    return result


def _is_target_http_error(error: HltvError) -> bool:
    """目标页面自身的 4xx/5xx 不需要重复解验证。"""
    return "目标页面返回 HTTP " in str(error)


async def _wait_flaresolverr_retry(attempt: int) -> None:
    """按尝试次数递增等待，避免连续撞击同一个验证页。"""
    delay = max(0.0, float(config.hltv_flaresolverr_retry_delay)) * (attempt + 1)
    if delay:
        await asyncio.sleep(delay)


async def _fetch_html(page_url: str) -> tuple[str, str]:
    """通过 FlareSolverr 获取页面 HTML 与最终地址。"""
    timeout_seconds = max(5.0, float(config.hltv_flaresolverr_timeout))
    base_payload: dict[str, object] = {
        "cmd": "request.get",
        "url": page_url,
        "maxTimeout": int(timeout_seconds * 1000),
    }
    wait_seconds = max(0.0, float(config.hltv_flaresolverr_wait_seconds))
    if wait_seconds:
        base_payload["waitInSeconds"] = wait_seconds
    proxy = _flaresolverr_proxy()
    if proxy:
        base_payload["proxy"] = proxy

    api_timeout = httpx.Timeout(
        timeout_seconds + 15.0,
        connect=min(10.0, timeout_seconds),
    )
    attempts = max(1, int(config.hltv_flaresolverr_retry_attempts))
    for attempt in range(attempts):
        try:
            # 不传 session 时 FlareSolverr 会在请求完成后自动关闭临时浏览器，
            # 避免低频查询留下常驻 Chromium 进程持续占用内存。
            result = await _call_flaresolverr(base_payload, timeout=api_timeout)
            if result.get("status") != "ok":
                message = str(result.get("message") or "未提供错误信息").strip()
                raise HltvError(f"FlareSolverr 未能获取页面：{message}")

            solution = result.get("solution")
            if not isinstance(solution, dict):
                raise HltvError("FlareSolverr 响应中缺少 solution。")
            solution_status = solution.get("status")
            if isinstance(solution_status, int) and solution_status >= 400:
                raise HltvError(f"目标页面返回 HTTP {solution_status}。")
            if isinstance(solution_status, str) and solution_status.isdigit():
                numeric_status = int(solution_status)
                if numeric_status >= 400:
                    raise HltvError(f"目标页面返回 HTTP {numeric_status}。")

            html = solution.get("response")
            if not isinstance(html, str) or not html.strip():
                raise HltvError("FlareSolverr 没有返回页面 HTML。")
            if _is_challenge_html(html):
                if attempt + 1 >= attempts:
                    raise HltvError("FlareSolverr 返回了未完成的浏览器验证页。")
                logger.warning(
                    f"FlareSolverr 返回未完成的验证页，将在第 "
                    f"{attempt + 2}/{attempts} 次重试：{page_url}"
                )
                await _wait_flaresolverr_retry(attempt)
                continue

            response_url = solution.get("url")
            if not isinstance(response_url, str) or not response_url.strip():
                response_url = page_url
            _remember_flaresolverr_session(solution)
            return html, response_url
        except HltvError as exc:
            if _is_target_http_error(exc) or attempt + 1 >= attempts:
                raise
            logger.warning(
                f"FlareSolverr 请求暂时失败，将在第 {attempt + 2}/{attempts} "
                f"次重试：{page_url} ({exc})"
            )
            await _wait_flaresolverr_retry(attempt)

    raise HltvError("FlareSolverr 未返回可用页面。")


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

    # HLTV 新版不保证 /events/<id> 是详情页，部分 ID 会返回 404 或通用首页。
    # 先访问结果入口，再从页面中的 event-hub-top 找到带 slug 的 canonical URL。
    candidates = [
        event_url(normalized_id, "results"),
        event_results_url(normalized_id),
        event_url(normalized_id, "matches"),
        event_url(normalized_id),
    ]
    tried: set[str] = set()
    while candidates:
        request_url = candidates.pop(0)
        if request_url in tried:
            continue
        tried.add(request_url)
        try:
            page_html, response_url = await _fetch_html(request_url)
        except HltvError:
            # 继续尝试新版结果入口、赛事 matches 页和其他候选地址。
            continue

        event = parse_event_html(
            page_html,
            event_id=normalized_id,
            page_url=response_url,
        )
        canonical_url = _canonical_event_url(
            page_html,
            event_id=normalized_id,
            page_url=response_url,
        )
        if event is not None:
            if canonical_url:
                event.url = canonical_url
            return event

        if canonical_url and canonical_url not in tried:
            candidates.insert(0, canonical_url)

    raise HltvError("没有从 HLTV 页面解析到赛事信息，可能是页面结构发生变化。")


async def fetch_event_match_refs(event_id: str) -> list[EventMatchRef]:
    """获取赛事的待进行比赛和历史结果链接。"""
    normalized_id = str(event_id).strip()
    if not normalized_id.isdigit():
        raise HltvError("赛事 ID 必须是纯数字。")

    pages = await asyncio.gather(
        _fetch_html(event_url(normalized_id, "matches")),
        _fetch_html(event_results_url(normalized_id)),
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
            event_id=normalized_id,
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


async def fetch_match(
    match_id: str,
    *,
    page_url: str | None = None,
) -> MatchData:
    """抓取并解析一场赛事；有完整链接时保留 HLTV 的 slug。"""
    normalized_id = str(match_id).strip()
    if not normalized_id.isdigit():
        raise HltvError("赛事 ID 必须是纯数字。")

    request_url = page_url.strip() if page_url else match_url(normalized_id)
    if page_url and match_id_from_url(request_url) != normalized_id:
        raise HltvError("比赛链接与赛事 ID 不一致。")

    html, response_url = await _fetch_html(request_url)
    match = parse_match_html(
        html,
        match_id=normalized_id,
        page_url=response_url,
    )
    if not match.teams:
        logger.warning("HLTV 页面未找到赛事队伍：%s", response_url)
        raise HltvError("没有从 HLTV 页面解析到赛事信息，可能是页面结构发生变化。")
    return match

