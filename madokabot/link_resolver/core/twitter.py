"""X/Twitter 帖子的元数据与媒体格式处理。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import httpx

from ..constants import FXTWITTER_STATUS_API

_STATUS_PATTERN = re.compile(
    r"https?://(?:(?:www|mobile)\.)?(?:x|twitter)\.com/"
    r"(?:(?P<screen_name>[A-Za-z0-9_]{1,20})/|i/web/)"
    r"status/(?P<status_id>\d+)",
    re.IGNORECASE,
)


class TwitterParseError(ValueError):
    """X 帖子解析失败。"""


@dataclass(frozen=True)
class TwitterMedia:
    """X 帖子中的一条媒体信息。"""

    kind: str
    url: str
    formats: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class TwitterPost:
    """FxTwitter 返回的 X 帖子信息。"""

    author_name: str
    author_screen_name: str
    text: str
    media: tuple[TwitterMedia, ...]


def _build_status_api_url(screen_name: str | None, status_id: str) -> str:
    """根据帖子链接构造 FxTwitter 接口地址。"""
    if screen_name:
        return FXTWITTER_STATUS_API.format(
            screen_name=screen_name,
            status_id=status_id,
        )
    return f"https://api.fxtwitter.com/status/{status_id}"


def _normalize_media(media_data: dict[str, Any]) -> tuple[TwitterMedia, ...]:
    """将 FxTwitter 的媒体字段整理为统一结构。"""
    raw_items = media_data.get("all")
    if not isinstance(raw_items, list):
        raw_items = []
        for key in ("photos", "videos"):
            items = media_data.get(key)
            if isinstance(items, list):
                raw_items.extend(items)

    media: list[TwitterMedia] = []
    for item in raw_items:
        if not isinstance(item, dict) or not item.get("url"):
            continue
        raw_formats = item.get("formats")
        formats = (
            tuple(
                format_info
                for format_info in raw_formats
                if isinstance(format_info, dict)
            )
            if isinstance(raw_formats, list)
            else ()
        )
        media.append(
            TwitterMedia(
                kind=str(item.get("type") or ""),
                url=str(item["url"]),
                formats=formats,
            )
        )
    return tuple(media)


async def fetch_twitter_post(url: str, proxy: str | None) -> TwitterPost:
    """通过 FxTwitter 获取 X 帖子的作者、正文和媒体列表。"""
    match = _STATUS_PATTERN.search(url)
    if not match:
        raise TwitterParseError("未识别到有效的 X 帖子链接")

    api_url = _build_status_api_url(
        match.group("screen_name"),
        match.group("status_id"),
    )
    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": "MadokaBot-LinkResolver/1.0"},
            proxy=proxy,
            timeout=20,
            follow_redirects=True,
            trust_env=False,
        ) as client:
            response = await client.get(api_url)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise TwitterParseError(f"FxTwitter 接口请求失败：{exc}") from exc

    if not isinstance(payload, dict):
        raise TwitterParseError("FxTwitter 返回数据格式无效")
    tweet = payload.get("tweet")
    if payload.get("code") != 200 or not isinstance(tweet, dict):
        message = payload.get("message") or "接口没有返回帖子数据"
        raise TwitterParseError(str(message))

    author = tweet.get("author")
    author = author if isinstance(author, dict) else {}
    media_data = tweet.get("media")
    media_data = media_data if isinstance(media_data, dict) else {}
    return TwitterPost(
        author_name=str(author.get("name") or ""),
        author_screen_name=str(author.get("screen_name") or ""),
        text=str(tweet.get("text") or ""),
        media=_normalize_media(media_data),
    )


def _format_height(format_info: dict[str, Any]) -> int:
    """读取视频格式的高度，缺少字段时从 FxTwitter URL 推断。"""
    height = format_info.get("height")
    if isinstance(height, (int, float)) and height > 0:
        return int(height)

    url = str(format_info.get("url") or "")
    match = re.search(r"/\d{2,5}x(?P<height>\d{2,5})/", url)
    return int(match.group("height")) if match else 0


def select_twitter_video_url(media: TwitterMedia) -> str | None:
    """只从 FxTwitter 返回的 MP4/H.264 格式中选择一个视频直链。"""
    candidates: list[tuple[int, float, str]] = []
    for format_info in media.formats:
        url = str(format_info.get("url") or "")
        if (
            not url
            or str(format_info.get("container") or "").casefold() != "mp4"
            or str(format_info.get("codec") or "").casefold() != "h264"
        ):
            continue
        try:
            bitrate = float(format_info.get("bitrate") or 0)
        except (TypeError, ValueError):
            bitrate = 0
        candidates.append((_format_height(format_info), bitrate, url))

    if not candidates:
        return None
    capped = [candidate for candidate in candidates if 0 < candidate[0] <= 720]
    return max(
        capped or candidates, key=lambda candidate: (candidate[0], candidate[1])
    )[2]
