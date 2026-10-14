"""小红书笔记页面与首屏评论读取。"""

import json
import re
from typing import Any

import httpx
from xhshow import Xhshow

from madokabot.core.resources import get_cookie_values, load_cookies

XHS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.xiaohongshu.com/",
    "Origin": "https://www.xiaohongshu.com",
}
_signer = Xhshow()


def create_xiaohongshu_client(proxy: str | None = None) -> httpx.AsyncClient:
    """使用统一 Netscape 资源创建按域名管理 Cookie 的客户端。"""
    return httpx.AsyncClient(
        cookies=load_cookies("xhs_cookies.txt"),
        headers=XHS_HEADERS,
        follow_redirects=True,
        trust_env=False,
        timeout=20,
        proxy=proxy,
    )


async def get_xiaohongshu_note(client: httpx.AsyncClient, url: str) -> dict[str, Any]:
    """展开分享链接并仅解码笔记详情段，不执行页面中的 JavaScript。"""
    response = await client.get(url)
    response.raise_for_status()
    id_match = re.search(r"/(?:explore|discovery/item)/([\da-f]+)", response.url.path)
    note_id = id_match[1] if id_match else response.url.params.get("noteId")
    state = re.search(
        r"window\.__INITIAL_STATE__\s*=\s*(.*?)</script>", response.text, re.DOTALL
    )
    if not note_id or not state:
        raise ValueError("未获取到小红书笔记，请检查分享链接、Cookie 和网络出口")
    marker = re.search(r'"noteDetailMap"\s*:\s*', state[1])
    if not marker:
        raise ValueError("小红书页面缺少笔记详情数据")
    # 只替换字符串之外的 undefined，保留正文中的原始文字。
    payload = re.sub(
        r'("(?:[^"\\]|\\.)*")|\bundefined\b',
        lambda match: match[1] or "null",
        state[1][marker.end() :].lstrip(),
    )
    details, _ = json.JSONDecoder().raw_decode(payload)
    note = details.get(note_id, {}).get("note")
    if not note:
        raise ValueError("小红书笔记不可见或分享链接已失效")
    if not note.get("xsecToken"):
        note["xsecToken"] = response.url.params.get("xsec_token", "")
    return note


def get_xiaohongshu_video_url(note: dict[str, Any]) -> str:
    """从实际流列表选择播放地址，优先 H.264 并保留最高码率。"""
    streams = [
        stream
        for group in note["video"]["media"]["stream"].values()
        for stream in group
        if stream.get("masterUrl")
    ]
    if not streams:
        raise ValueError("小红书笔记没有可用的视频播放地址")
    selected = min(
        streams,
        key=lambda stream: (
            stream.get("videoCodec") != "h264",
            -stream.get("avgBitrate", 0),
        ),
    )
    return selected["masterUrl"]


async def get_xiaohongshu_comments(
    client: httpx.AsyncClient, note: dict[str, Any]
) -> list[dict[str, Any]]:
    """用同一会话签名读取最多十条首屏评论，不翻页抓取。"""
    uri = "/api/sns/web/v2/comment/page"
    api_url = "https://edith.xiaohongshu.com" + uri
    params = {
        "note_id": note["noteId"],
        "cursor": "",
        "top_comment_id": "",
        "image_formats": "jpg,webp,avif",
        "xsec_token": note.get("xsecToken", ""),
    }
    cookies = get_cookie_values(client.cookies.jar, api_url)
    if not cookies.get("a1"):
        raise ValueError("小红书 Cookie 缺少 a1 设备标识，无法签名读取评论")
    headers = _signer.sign_headers_get(uri=uri, cookies=cookies, params=params)
    response = await client.get(_signer.build_url(api_url, params), headers=headers)
    response.raise_for_status()
    data = response.json()
    if not data.get("success"):
        raise ValueError("小红书评论接口未返回成功结果，请检查 Cookie 或请求签名")
    return (data.get("data", {}).get("comments") or [])[:10]
