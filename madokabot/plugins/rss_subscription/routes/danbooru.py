import asyncio
from html import escape
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
from yarl import URL

from ..config import config
from ..images import (
    handle_img_combo,
    handle_img_combo_with_content,
    handle_video_combo,
)
from ..parser import HandlerRegistry
from ..subscription import Rss


DANBOORU_HOST = "danbooru.donmai.us"
DANBOORU_POST_PATHS = {"/posts", "/posts.atom", "/posts.json"}
VIDEO_EXTENSIONS = {"mp4", "webm", "m4v", "mov"}
RATING_NAMES = {
    "g": "普通",
    "s": "敏感",
    "q": "可疑",
    "e": "露骨",
}
_request_lock = asyncio.Lock()
_last_request_at = 0.0


class DanbooruAPIError(RuntimeError):
    """Danbooru API returned data in an unexpected shape."""


def is_danbooru_url(url: str) -> bool:
    parsed = URL(url)
    return (
        parsed.host == DANBOORU_HOST
        and parsed.path.rstrip("/") in DANBOORU_POST_PATHS
    )


def _api_url(url: str) -> URL:
    parsed = URL(url)
    query = [(key, value) for key, value in parsed.query.items() if key != "format"]
    return parsed.with_path("/posts.json").with_query(query)


def _api_user_agent() -> str:
    user_agent = "MadokaBot-RSS/1.0"
    if config.danbooru_user_id is not None:
        user_agent += f" (user #{config.danbooru_user_id})"
    return user_agent


def _api_auth() -> Optional[aiohttp.BasicAuth]:
    if config.danbooru_login and config.danbooru_api_key:
        return aiohttp.BasicAuth(
            config.danbooru_login,
            config.danbooru_api_key.get_secret_value(),
        )
    return None


def _display_tags(value: Any) -> str:
    return str(value or "").replace("_", " ")


def _post_to_entry(post: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    post_id = post.get("id")
    if not post_id:
        return None

    post_url = f"https://{DANBOORU_HOST}/posts/{post_id}"
    file_ext = str(post.get("file_ext") or "").lower()
    is_video = file_ext in VIDEO_EXTENSIONS
    preview_url = str(post.get("preview_file_url") or "")
    original_url = str(post.get("file_url") or "")
    large_url = str(post.get("large_file_url") or "")
    media_url = (
        (original_url or large_url or preview_url)
        if is_video
        else large_url or original_url or preview_url
    )

    character_tags = _display_tags(post.get("tag_string_character"))
    copyright_tags = _display_tags(post.get("tag_string_copyright"))
    if not character_tags and not copyright_tags:
        return None

    details: List[str] = [
        f"评分：{post.get('score', 0)}",
        f"分级：{RATING_NAMES.get(str(post.get('rating') or ''), '未知')}",
    ]
    for label, field in (
        ("作者", "tag_string_artist"),
        ("角色", "tag_string_character"),
        ("作品", "tag_string_copyright"),
    ):
        if value := _display_tags(post.get(field)):
            details.append(f"{label}：{value}")
    if source := str(post.get("source") or ""):
        details.append(
            f'来源：<a href="{escape(source, quote=True)}">{escape(source)}</a>'
        )

    summary = "<p>" + "<br>".join(details) + "</p>"
    if media_url:
        summary += f'<img src="{escape(media_url, quote=True)}">'

    return {
        "guid": post_url,
        "link": post_url,
        "title": f"Danbooru Post #{post_id}",
        "author": _display_tags(post.get("tag_string_artist")),
        "published": post.get("created_at"),
        "updated": post.get("updated_at"),
        "summary": summary,
        "imageboard_character": character_tags,
        "imageboard_copyright": copyright_tags,
        "danbooru_media_url": media_url,
        "danbooru_original_url": original_url,
        "danbooru_file_ext": file_ext,
        "danbooru_is_video": is_video,
        "image_headers": {
            "Referer": f"https://{DANBOORU_HOST}/",
            "User-Agent": _api_user_agent(),
        },
    }


async def fetch_danbooru(
    rss: Rss, proxy: Optional[str]
) -> Tuple[Dict[str, Any], bool, Dict[str, str]]:
    """Fetch a Danbooru post search through the official JSON API."""
    global _last_request_at

    headers = {
        "Accept": "application/json",
        "User-Agent": _api_user_agent(),
    }
    if not config.debug:
        if rss.etag:
            headers["If-None-Match"] = rss.etag
        if rss.last_modified:
            headers["If-Modified-Since"] = rss.last_modified

    async with _request_lock:
        loop = asyncio.get_running_loop()
        wait_time = 1.0 - (loop.time() - _last_request_at)
        if wait_time > 0:
            await asyncio.sleep(wait_time)

        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(
                headers=headers, timeout=timeout
            ) as session:
                async with session.get(
                    _api_url(rss.get_url()),
                    proxy=proxy,
                    auth=_api_auth(),
                ) as response:
                    response_headers = dict(response.headers)
                    if response.status == 304:
                        return {}, True, response_headers
                    response.raise_for_status()
                    payload = await response.json(content_type=None)
        finally:
            _last_request_at = loop.time()

    if not isinstance(payload, list):
        raise DanbooruAPIError("Danbooru API 没有返回作品列表")

    entries = [entry for post in payload if (entry := _post_to_entry(post))]
    tags = _api_url(rss.get_url()).query.get("tags", "")
    title = f"Danbooru: {tags}" if tags else "Danbooru Posts"
    return {"feed": {"title": title}, "entries": entries}, False, response_headers


@HandlerRegistry.append_handler(parsing_type="picture", rex="danbooru")
async def handle_picture(rss: Rss, item: Dict[str, Any], tmp: str) -> str:
    if rss.only_title:
        return ""

    media_url = str(item.get("danbooru_media_url") or "")
    if not media_url:
        result = "图片地址不可用"
    elif item.get("danbooru_is_video"):
        result = await handle_video_combo(
            media_url, rss.img_proxy, rss, item.get("image_headers")
        )
    elif item.get("image_content"):
        result = await handle_img_combo_with_content(
            media_url, item["image_content"], rss
        )
    else:
        result = await handle_img_combo(
            media_url, rss.img_proxy, rss, item.get("image_headers")
        )

    return f"{result}\n" if rss.only_pic else f"{tmp + result}\n"
