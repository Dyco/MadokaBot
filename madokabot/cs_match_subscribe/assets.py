"""HLTV 队标、国旗和选手图缓存。"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import mimetypes
import re
from pathlib import Path
from urllib.parse import urlparse

from nonebot.log import logger
from playwright.async_api import BrowserContext, Error as PlaywrightError, async_playwright

from ..madoka_bundle.config import assets as resource_assets
from ..madoka_bundle.config import config as madoka_config
from ..madoka_bundle.constants import ResType, SubFolder
from ..madoka_bundle.utils import get_file, get_files
from .client import FlaresolverrSession, get_flaresolverr_session
from .config import config, ensure_asset_dirs
from .models import EventData, MatchData

_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/avif": ".avif",
    "image/svg+xml": ".svg",
}
_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".avif": "image/avif",
    ".svg": "image/svg+xml",
}
_SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9._-]+")
_CSTEAM_CATEGORIES = {"team", "flag"}


def _asset_proxy() -> str | None:
    value = (
        config.hltv_flaresolverr_proxy
        or config.hltv_proxy
        or madoka_config.proxy
    )
    if value is None:
        return None
    proxy = str(value).strip()
    if not proxy:
        return None
    return proxy if "://" in proxy else f"http://{proxy}"


def _asset_stem(url: str, category: str) -> str:
    parsed = urlparse(url)
    source_name = Path(parsed.path).name or category
    source_name = _SAFE_NAME_RE.sub("-", source_name).strip("-") or category
    return Path(source_name).stem[:40] or category


def _asset_name(url: str, category: str, content_type: str | None = None) -> str:
    parsed = urlparse(url)
    source_name = Path(parsed.path).name or category
    source_name = _SAFE_NAME_RE.sub("-", source_name).strip("-") or category
    suffix = Path(source_name).suffix.lower()
    normalized_type = (content_type or "").split(";", 1)[0].lower()
    if normalized_type in _EXTENSIONS:
        suffix = _EXTENSIONS[normalized_type]
    elif suffix not in _MIME_TYPES:
        suffix = ".png"
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return f"{category}-{_asset_stem(url, category)}-{digest}{suffix}"


def _data_url(path: Path) -> str:
    mime = _MIME_TYPES.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _placeholder_data_url(label: str, category: str) -> str:
    """资源下载失败时使用内联 SVG，避免 Playwright 等待外链超时。"""
    safe_label = (label[:2] or "?").upper()
    color = "#d9dde2" if category == "flag" else "#eef0f3"
    foreground = "#59636e"
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="50" height="30" '
        f'viewBox="0 0 50 30"><rect width="50" height="30" rx="3" fill="{color}"/>'
        f'<text x="25" y="20" text-anchor="middle" font-family="Arial" '
        f'font-size="11" fill="{foreground}">{safe_label}</text></svg>'
    )
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def _asset_dir(category: str) -> Path:
    """返回资源分类目录；队标和国旗使用通用 CSTEAM 资源目录。"""
    if category in _CSTEAM_CATEGORIES:
        return resource_assets.get_dir(ResType.IMAGE, SubFolder.CSTEAM)
    return ensure_asset_dirs() / category


def _find_cached_asset(url: str, category: str) -> Path | None:
    """按 URL 哈希查找本地图片，队标和国旗优先走 assets/image/csteam。"""
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    target_dir = _asset_dir(category)
    if category in _CSTEAM_CATEGORIES:
        expected_name = _asset_name(url, category, "image/png")
        cached = get_file(ResType.IMAGE, SubFolder.CSTEAM, expected_name)
        if cached is not None and cached.stat().st_size:
            return cached
        # 兼容同一 URL 曾以其他图片扩展名保存的本地资源。
        cached_files = get_files(ResType.IMAGE, SubFolder.CSTEAM)
        exact_cached = next(
            (
                path
                for path in cached_files
                if path.name.startswith(f"{category}-")
                and digest in path.name
                and path.stat().st_size
            ),
            None,
        )
        if exact_cached is not None:
            return exact_cached
        return next(
            (
                path
                for path in cached_files
                if path.name.startswith(f"{category}-{_asset_stem(url, category)}-")
                and path.stat().st_size
            ),
            None,
        )

    cached_candidates = list(target_dir.glob(f"{category}-*"))
    return next(
        (
            path
            for path in cached_candidates
            if digest in path.name and path.is_file() and path.stat().st_size
        ),
        None,
    )


def _playwright_cookies(session: FlaresolverrSession) -> list[dict[str, object]]:
    """转换为 Playwright 可接受的 Cookie 字段。"""
    cookies: list[dict[str, object]] = []
    for raw_cookie in session.cookies:
        cookie = dict(raw_cookie)
        if not cookie.get("domain") and not cookie.get("url"):
            continue
        expires = cookie.get("expires")
        if (
            not isinstance(expires, (int, float))
            or isinstance(expires, bool)
            or expires <= 0
        ):
            cookie.pop("expires", None)
        cookies.append(cookie)
    return cookies


async def _download_one(
    context: BrowserContext,
    url: str,
    *,
    category: str,
    label: str,
    timeout_ms: int,
) -> Path | None:
    target_dir = _asset_dir(category)
    target_dir.mkdir(parents=True, exist_ok=True)
    cached = _find_cached_asset(url, category)
    if cached is not None and cached.is_file() and cached.stat().st_size:
        return cached

    page = None
    try:
        page = await context.new_page()
        response = await page.goto(url, wait_until="load", timeout=timeout_ms)
        if response is not None and response.status >= 400:
            logger.warning("HLTV 资源浏览器请求失败：%s (HTTP %s)", url, response.status)
            return None
        if response is None:
            logger.warning("HLTV 资源浏览器没有返回响应：%s", url)
            return None

        content_type = (
            await response.header_value("content-type") or ""
        ).split(";", 1)[0].strip().lower()
        if not content_type.startswith("image/"):
            logger.warning(
                "HLTV 资源响应不是图片，已跳过：%s (%s)",
                url,
                content_type or "未知类型",
            )
            return None

        # 直接保存 HTTP 响应，保留队标 PNG/SVG 原本的透明通道。
        # 不能对 img 元素截图，否则透明区域会被浏览器图片文档的背景色填充。
        content = await response.body()
        if not content:
            logger.warning("HLTV 资源响应为空：%s", url)
            return None
        if len(content) > config.hltv_max_asset_size:
            logger.warning("HLTV 资源过大，已跳过：%s", url)
            return None
        path = target_dir / _asset_name(url, category, content_type)
        path.write_bytes(content)
        return path
    except (PlaywrightError, OSError) as exc:
        logger.warning("下载 HLTV %s 失败（%s）：%s", label, url, exc)
        return None
    finally:
        if page is not None:
            await page.close()


async def _download_assets(
    refs: dict[str, tuple[str, str]],
    *,
    referer: str,
) -> dict[str, Path | None]:
    """复用 FlareSolverr 的浏览器会话，通过 Playwright 下载图片。"""
    if not refs:
        return {}

    results: dict[str, Path | None] = {}
    missing_refs: dict[str, tuple[str, str]] = {}
    for url, reference in refs.items():
        cached = _find_cached_asset(url, reference[0])
        results[url] = cached
        if cached is None:
            missing_refs[url] = reference
    if not missing_refs:
        return results

    session = get_flaresolverr_session()
    if session is None:
        logger.warning("没有可复用的 FlareSolverr 浏览器会话，跳过 HLTV 图片下载。")
        return results

    launch_options: dict[str, object] = {"headless": True}
    proxy = _asset_proxy()
    if proxy:
        launch_options["proxy"] = {"server": proxy}

    timeout_ms = max(1_000, int(float(config.hltv_request_timeout) * 1000))
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(**launch_options)
            try:
                context_options: dict[str, object] = {
                    "viewport": {"width": 1280, "height": 900},
                }
                if session.user_agent:
                    context_options["user_agent"] = session.user_agent
                context = await browser.new_context(**context_options)
                try:
                    cookies = _playwright_cookies(session)
                    if cookies:
                        await context.add_cookies(cookies)
                    await context.set_extra_http_headers(
                        {
                            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                            "Referer": referer,
                        }
                    )
                    semaphore = asyncio.Semaphore(4)

                    async def download(url: str) -> tuple[str, Path | None]:
                        async with semaphore:
                            category, label = missing_refs[url]
                            return url, await _download_one(
                                context,
                                url,
                                category=category,
                                label=label,
                                timeout_ms=timeout_ms,
                            )

                    results.update(
                        dict(
                            await asyncio.gather(
                                *(download(url) for url in missing_refs)
                            )
                        )
                    )
                    return results
                finally:
                    await context.close()
            finally:
                await browser.close()
    except (PlaywrightError, OSError) as exc:
        logger.warning("启动 HLTV 资源浏览器失败：%s", exc)
        return results


async def enrich_match_assets(match: MatchData) -> MatchData:
    """下载并将赛事图片转换为渲染可直接使用的 data URL。"""
    refs: dict[str, tuple[str, str]] = {}
    team_groups = [match.teams, *match.map_stats.values()]
    for teams in team_groups:
        for team in teams:
            if team.logo_url:
                refs.setdefault(team.logo_url, ("team", team.name))
            for player in team.players:
                if player.flag_url:
                    refs.setdefault(player.flag_url, ("flag", player.nickname))

    if not refs:
        return match

    results = await _download_assets(
        refs,
        referer=match.url or str(config.hltv_base_url).rstrip("/") + "/",
    )

    for teams in team_groups:
        for team in teams:
            if team.logo_url:
                path = results.get(team.logo_url)
                team.logo_src = _data_url(path) if path else None
            for player in team.players:
                if player.flag_url:
                    path = results.get(player.flag_url)
                    player.flag_src = _data_url(path) if path else None
    return match


async def enrich_event_assets(events: list[EventData]) -> list[EventData]:
    """下载赛事横幅和国旗，并转换为渲染可直接使用的 data URL。"""
    refs: dict[str, tuple[str, str]] = {}
    for event in events:
        if event.banner_url:
            refs.setdefault(event.banner_url, ("event", event.name))
        if event.flag_url:
            refs.setdefault(event.flag_url, ("flag", event.location))

    if not refs:
        return events

    referer = next((event.url for event in events if event.url), "")
    results = await _download_assets(
        refs,
        referer=referer or str(config.hltv_base_url).rstrip("/") + "/",
    )

    for event in events:
        if event.banner_url:
            path = results.get(event.banner_url)
            event.banner_src = _data_url(path) if path else _placeholder_data_url(event.name, "event")
        if event.flag_url:
            path = results.get(event.flag_url)
            event.flag_src = _data_url(path) if path else None
    return events
