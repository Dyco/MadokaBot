"""小红书图文、视频与评论解析事件处理器。"""

import re
from pathlib import Path

import aiohttp
import httpx
from nonebot import logger
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageSegment
from playwright.async_api import Error as PlaywrightError

from ..commands import comment_mode_map, resolve_controller, resolve_handler
from ..comments import (
    escape_html,
    format_comments_to_nodes,
    parse_xiaohongshu_comments,
    render_comments_image,
)
from ..delivery import send_resolved_video
from ..downloads import download_image
from ..matchers import XIAOHONGSHU_PATTERN
from ..matchers import xiaohongshu_matcher as xhs
from ..messages import (
    get_resolver_message,
    get_target_id,
    make_forward_nodes,
    send_forward,
)
from ..sources.xiaohongshu import (
    XHS_HEADERS,
    create_xiaohongshu_client,
    get_xiaohongshu_comments,
    get_xiaohongshu_note,
    get_xiaohongshu_video_url,
)
from ..state import is_content_enabled
from .runtime import GLOBAL_NICKNAME, XIAOHONGSHU_PROXY
from .video import _find_video_duration_seconds, _skip_video_for_duration


async def _comment_nodes(
    client: httpx.AsyncClient, note: dict, bot_id: str, target_id: int
) -> list[MessageSegment]:
    """按群评论开关及展示模式生成节点，评论失败不影响笔记解析。"""
    if not is_content_enabled(target_id, "xiaohongshu", "comment"):
        return []
    try:
        comments = parse_xiaohongshu_comments(
            await get_xiaohongshu_comments(client, note),
            note.get("user", {}).get("userId", ""),
        )
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning(f"[小红书] 评论获取失败，跳过评论：{type(exc).__name__}")
        return []
    if not comments:
        return []
    title = note.get("title") or "小红书笔记"
    if comment_mode_map.get(str(target_id), "image") == "image" and is_content_enabled(
        target_id, "xiaohongshu", "image"
    ):
        try:
            image = await render_comments_image(comments, escape_html(title))
            return [make_forward_nodes(bot_id, MessageSegment.image(image))]
        except (ImportError, OSError, RuntimeError, PlaywrightError) as exc:
            logger.warning(f"[小红书] 评论图片渲染失败，改用文字：{type(exc).__name__}")
    return format_comments_to_nodes(bot_id, comments, title, GLOBAL_NICKNAME)


@xhs.handle()
@resolve_handler
@resolve_controller
async def xiaohongshu(bot: Bot, event: GroupMessageEvent) -> None:
    """使用 Netscape Cookie 解析笔记及评论，视频关闭时仅发送图文信息。"""
    message_text = get_resolver_message(event).replace("&amp;", "&")
    url_match = re.search(
        XIAOHONGSHU_PATTERN,
        message_text,
        re.IGNORECASE,
    )
    if not url_match:
        return
    target_id = get_target_id(event)
    try:
        async with create_xiaohongshu_client(XIAOHONGSHU_PROXY) as client:
            note = await get_xiaohongshu_note(client, url_match[0])
            comment_nodes = await _comment_nodes(client, note, bot.self_id, target_id)
    except FileNotFoundError:
        logger.warning("[小红书] 未找到 Cookie 资源：assets/cookies/xhs_cookies.txt")
        return
    except (OSError, httpx.HTTPError, ValueError) as exc:
        logger.warning(f"[小红书] 笔记获取失败：{type(exc).__name__}")
        return

    info = MessageSegment.text(
        f"{GLOBAL_NICKNAME}识别：小红书\n标题：{note.get('title', '')}\n{note.get('desc', '')}"
    )
    nodes = list(make_forward_nodes(bot.self_id, [info]))
    if note["type"] == "normal":
        paths = []
        try:
            if is_content_enabled(target_id, "xiaohongshu", "image"):
                async with aiohttp.ClientSession(trust_env=False) as session:
                    for image in note["imageList"]:
                        paths.append(
                            await download_image(
                                image["urlDefault"],
                                proxy=XIAOHONGSHU_PROXY,
                                session=session,
                                headers=XHS_HEADERS,
                            )
                        )
                nodes.extend(
                    make_forward_nodes(
                        bot.self_id,
                        [
                            MessageSegment.image(Path(path).resolve().as_uri())
                            for path in paths
                        ],
                    )
                )
            await send_forward(bot, event, [*nodes, *comment_nodes])
        finally:
            for path in paths:
                Path(path).unlink(missing_ok=True)
    elif note["type"] == "video":
        await send_forward(bot, event, [*nodes, *comment_nodes])
        if not is_content_enabled(target_id, "xiaohongshu", "video"):
            return
        if _skip_video_for_duration(
            "小红书", _find_video_duration_seconds(note.get("video"))
        ):
            return
        try:
            video_url = get_xiaohongshu_video_url(note)
        except ValueError as exc:
            await xhs.finish(str(exc))
        await send_resolved_video(event, video_url, XIAOHONGSHU_PROXY)
    else:
        await xhs.finish(f"暂不支持的小红书内容类型：{note['type']}")
