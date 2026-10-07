"""xiaohongshu 链接解析事件处理器。"""

import asyncio
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import aiohttp
import httpx
from nonebot import logger
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageSegment

from madokabot.core.messaging.media import MediaSizeLimitExceeded

from ..commands import resolve_controller, resolve_handler
from ..constants import (
    COMMON_HEADER,
    XHS_REQ_LINK,
)
from ..delivery import media_delivery, send_resolved_video
from ..downloads import (
    CACHE_DIR,
    download_image,
    download_video,
)
from ..matchers import (
    xiaohongshu_matcher as xhs,
)
from ..messages import (
    get_resolver_message,
    make_forward_nodes,
    send_forward,
)
from .runtime import (
    GLOBAL_NICKNAME,
    XIAOHONGSHU_PROXY,
    global_config,
)
from .video import (
    _find_video_duration_seconds,
    _skip_video_for_duration,
)


@xhs.handle()
@resolve_handler
@resolve_controller
async def xiaohongshu(bot: Bot, event: GroupMessageEvent):
    """小红书解析方法。"""
    message_text = get_resolver_message(event).replace("&amp;", "&")
    url_match = re.search(
        r"https?://(?:xhslink|(?:www\.)?xiaohongshu)\.com/"
        r"[A-Za-z\d._?%&+\-=/#@]*",
        message_text,
    )
    if not url_match:
        await xhs.finish("未识别到有效的小红书链接。")
    msg_url = url_match.group(0)
    xhs_ck = getattr(global_config, "xhs_ck", "")
    if xhs_ck == "":
        logger.error(global_config)
        await send_forward(
            bot,
            event,
            make_forward_nodes(
                bot.self_id,
                MessageSegment.text(
                    f"{GLOBAL_NICKNAME}识别内容来自：【小红书】\n无法获取到管理员设置的小红书ck！"
                ),
            ),
        )
        return
    headers = {
        "accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/webp,image/apng,*/*;q=0.8,"
            "application/signed-exchange;v=b3;q=0.9"
        ),
        "cookie": xhs_ck,
    } | COMMON_HEADER
    if "xhslink" in msg_url:
        msg_url = httpx.get(
            msg_url,
            headers=headers,
            follow_redirects=True,
            proxy=XIAOHONGSHU_PROXY,
            timeout=20,
            trust_env=False,
        ).url
        msg_url = str(msg_url)
    xhs_id = re.search(r"/explore/(\w+)", msg_url)
    if not xhs_id:
        xhs_id = re.search(r"/discovery/item/(\w+)", msg_url)
    if not xhs_id:
        xhs_id = re.search(r"source=note&noteId=(\w+)", msg_url)
    if not xhs_id:
        await xhs.finish("无法从小红书链接中提取笔记 ID。")
    xhs_id = xhs_id.group(1)
    parsed_url = urlparse(msg_url)
    params = parse_qs(parsed_url.query)
    xsec_source = params.get("xsec_source", [None])[0] or "pc_feed"
    xsec_token = params.get("xsec_token", [None])[0]

    html = httpx.get(
        f"{XHS_REQ_LINK}{xhs_id}?xsec_source={xsec_source}&xsec_token={xsec_token}",
        headers=headers,
        proxy=XIAOHONGSHU_PROXY,
        timeout=20,
        trust_env=False,
    ).text
    try:
        response_json = re.findall("window.__INITIAL_STATE__=(.*?)</script>", html)[0]
    except IndexError:
        await send_forward(
            bot,
            event,
            make_forward_nodes(
                bot.self_id,
                MessageSegment.text(
                    f"{GLOBAL_NICKNAME}识别内容来自：【小红书】\n当前ck已失效，请联系管理员重新设置的小红书ck！"
                ),
            ),
        )
        return
    response_json = response_json.replace("undefined", "null")
    response_json = json.loads(response_json)
    note_data = response_json["note"]["noteDetailMap"][xhs_id]["note"]
    type = note_data["type"]
    note_title = note_data["title"]
    note_desc = note_data["desc"]
    xhs_info_node = make_forward_nodes(
        bot.self_id,
        MessageSegment.text(
            f"{GLOBAL_NICKNAME}识别：小红书\n标题：{note_title}\n{note_desc}"
        ),
    )

    aio_task = []
    if type == "normal":
        image_list = note_data["imageList"]
        async with aiohttp.ClientSession(
            proxy=XIAOHONGSHU_PROXY,
            trust_env=False,
        ) as session:
            for index, item in enumerate(image_list):
                aio_task.append(
                    asyncio.create_task(
                        download_image(
                            item["urlDefault"],
                            str(CACHE_DIR / f"{index}.jpg"),
                            proxy=XIAOHONGSHU_PROXY,
                            session=session,
                        )
                    )
                )
            links_path = await asyncio.gather(*aio_task)
    elif type == "video":
        logger.info(note_data["video"])

        video_url = note_data["video"]["media"]["stream"]["h264"][0]["masterUrl"]

        await send_forward(bot, event, xhs_info_node)
        if _skip_video_for_duration(
            "小红书",
            _find_video_duration_seconds(note_data.get("video")),
        ):
            return
        try:
            path = await download_video(
                video_url,
                XIAOHONGSHU_PROXY,
                max_size=media_delivery.video_compress_limit,
            )
        except MediaSizeLimitExceeded as exc:
            logger.warning(f"[小红书] 视频超过大小限制，已跳过下载和发送：{exc}")
            return
        except ValueError as exc:
            await xhs.finish(f"视频无法下载：{exc}")
        await send_resolved_video(event, path, XIAOHONGSHU_PROXY)
        return
    else:
        await xhs.finish(f"暂不支持的小红书内容类型：{type}")

    xhs_forward_nodes = [xhs_info_node]
    xhs_forward_nodes.extend(
        make_forward_nodes(
            bot.self_id,
            [
                MessageSegment.image(file=Path(link).resolve().as_uri())
                for link in links_path
            ],
        )
    )
    await send_forward(bot, event, xhs_forward_nodes)
    for temp in links_path:
        Path(temp).unlink(missing_ok=True)
