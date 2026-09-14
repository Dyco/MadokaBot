"""HLTV 队标、国旗和选手图缓存。"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import mimetypes
import re
from pathlib import Path
from urllib.parse import urlparse

import httpx
from nonebot.log import logger

from ..madoka_bundle.config import config as madoka_config
from .config import config, ensure_asset_dirs
from .models import MatchData


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


def _proxy() -> str | None:
    value = config.hltv_proxy or madoka_config.proxy
    if value is None:
        return None
    proxy = str(value).strip()
    if not proxy:
        return None
    return proxy if "://" in proxy else f"http://{proxy}"


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
    stem = Path(source_name).stem[:40] or category
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return f"{category}-{stem}-{digest}{suffix}"


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


async def _download_one(
    client: httpx.AsyncClient,
    url: str,
    *,
    category: str,
    label: str,
) -> Path | None:
    target_dir = ensure_asset_dirs() / category
    target_dir.mkdir(parents=True, exist_ok=True)
    cached_candidates = list(target_dir.glob(f"{category}-*"))
    # 文件名含 URL 哈希；避免每次请求都触发网络访问。
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    cached = next((path for path in cached_candidates if digest in path.name), None)
    if cached is not None and cached.is_file() and cached.stat().st_size:
        return cached

    try:
        response = await client.get(url)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if not content_type.lower().startswith("image/"):
            logger.warning("HLTV 资源不是图片，已跳过：%s (%s)", url, content_type)
            return None
        if len(response.content) > config.hltv_max_asset_size:
            logger.warning("HLTV 资源过大，已跳过：%s", url)
            return None
        path = target_dir / _asset_name(url, category, content_type)
        path.write_bytes(response.content)
        return path
    except (httpx.HTTPError, OSError) as exc:
        logger.warning("下载 HLTV %s 失败（%s）：%s", label, url, exc)
        return None


async def enrich_match_assets(match: MatchData) -> MatchData:
    """下载并将赛事图片转换为渲染可直接使用的 data URL。"""
    refs: dict[str, tuple[str, str]] = {}
    for team in match.teams:
        if team.logo_url:
            refs.setdefault(team.logo_url, ("team", team.name))
        for player in team.players:
            if player.flag_url:
                refs.setdefault(player.flag_url, ("flag", player.nickname))
            if player.photo_url:
                refs.setdefault(player.photo_url, ("player", player.nickname))

    if not refs:
        return match

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; MadokaBot/1.0; +https://github.com/Dyco/MadokaBot)",
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "Referer": str(config.hltv_base_url).rstrip("/") + "/",
    }
    limits = httpx.Limits(max_connections=8, max_keepalive_connections=4)
    async with httpx.AsyncClient(
        proxy=_proxy(),
        trust_env=False,
        follow_redirects=True,
        headers=headers,
        timeout=httpx.Timeout(config.hltv_request_timeout, connect=10.0),
        limits=limits,
    ) as client:
        semaphore = asyncio.Semaphore(8)

        async def download(url: str) -> tuple[str, Path | None]:
            async with semaphore:
                category, label = refs[url]
                return url, await _download_one(
                    client,
                    url,
                    category=category,
                    label=label,
                )

        results = dict(await asyncio.gather(*(download(url) for url in refs)))

    for team in match.teams:
        if team.logo_url:
            path = results.get(team.logo_url)
            team.logo_src = _data_url(path) if path else _placeholder_data_url(team.name, "team")
        for player in team.players:
            if player.flag_url:
                path = results.get(player.flag_url)
                player.flag_src = _data_url(path) if path else _placeholder_data_url(player.nickname, "flag")
            if player.photo_url:
                path = results.get(player.photo_url)
                player.photo_src = _data_url(path) if path else _placeholder_data_url(player.nickname, "player")
    return match
