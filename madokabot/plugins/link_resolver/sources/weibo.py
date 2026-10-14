"""微博网页接口、卡片跳转及媒体地址提取。"""

import re
from typing import Any

import httpx

from madokabot.core.resources import load_cookies

WEIBO_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
    ),
    "Referer": "https://weibo.com/",
}


def create_weibo_client(proxy: str | None = None) -> httpx.AsyncClient:
    """读取统一 Netscape 资源，按域名发送 Cookie 且不回写原文件。"""
    return httpx.AsyncClient(
        cookies=load_cookies("weibo_cookies.txt"),
        headers=WEIBO_HEADERS,
        proxy=proxy,
        timeout=20,
        trust_env=False,
    )


def _post_id(url: httpx.URL) -> str | None:
    """从支持的微博地址提取数字编号或短编号，不进行进制转换。"""
    if url.host not in {"weibo.com", "www.weibo.com", "m.weibo.cn"}:
        return None
    if url.path.startswith("/tv/show/"):
        mid = url.params.get("mid", "")
        return mid if mid.isdecimal() else None
    match = re.fullmatch(r"/(?:\d+|detail|status)/([A-Za-z0-9]+)/?", url.path)
    return match[1] if match else None


async def get_weibo_post(client: httpx.AsyncClient, url: str) -> dict[str, Any]:
    """展开卡片后读取网页作品接口，并为长微博补齐完整正文。"""
    target = httpx.URL(url)
    if target.host == "mapp.api.weibo.cn":
        response = await client.get(target)
        location = response.headers.get("location")
        if not response.is_redirect or not location:
            raise ValueError("微博卡片未返回有效的作品跳转地址")
        # 只读取跳转地址中的编号，不请求移动端访客验证页。
        target = response.url.join(location)
    post_id = _post_id(target)
    if not post_id:
        raise ValueError("无法从微博分享链接提取作品编号")
    # 与 yt-dlp 的微博提取器使用同一网页作品接口。
    response = await client.get(
        "https://weibo.com/ajax/statuses/show", params={"id": post_id}
    )
    response.raise_for_status()
    post = response.json()
    if not isinstance(post, dict) or post.get("ok") != 1 or not post.get("idstr"):
        raise ValueError("微博接口未返回作品，请检查 Cookie 是否有效及作品是否可见")
    if post.get("isLongText"):
        response = await client.get(
            "https://weibo.com/ajax/statuses/longtext", params={"id": post_id}
        )
        response.raise_for_status()
        long_text = response.json()
        if long_text.get("ok") == 1:
            post["text_raw"] = long_text["data"]["longTextContent_raw"]
    return post


def get_weibo_images(post: dict[str, Any]) -> list[str]:
    """按作品中的原始顺序提取原图地址。"""
    pictures = post.get("pic_infos") or {}
    return [
        url
        for pic_id in post.get("pic_ids") or []
        if (url := pictures.get(pic_id, {}).get("original", {}).get("url"))
    ]


def get_weibo_video_url(post: dict[str, Any]) -> str:
    """优先从网页播放列表选择接近 720p 的流，也支持直链字段。"""
    media = (post.get("page_info") or {}).get("media_info") or {}
    streams = [
        item["play_info"]
        for item in media.get("playback_list") or []
        if item.get("play_info", {}).get("url")
    ]
    if streams:
        stream = min(
            streams, key=lambda item: abs(int(item.get("height") or 720) - 720)
        )
        return stream["url"]
    return media.get("stream_url_hd") or media.get("stream_url") or ""
