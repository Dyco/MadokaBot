"""weibo 链接解析事件处理器。"""

import asyncio
import json
import re
from pathlib import Path

import httpx
from nonebot import logger
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageSegment

from madokabot.core.messaging.media import MediaSizeLimitExceeded

from ..commands import resolve_controller, resolve_handler
from ..constants import (
    COMMON_HEADER,
    WEIBO_SINGLE_INFO,
)
from ..delivery import media_delivery, send_resolved_video
from ..downloads import (
    download_image,
    download_video,
)
from ..matchers import (
    weibo_matcher as weibo,
)
from ..messages import (
    get_resolver_message,
    make_forward_nodes,
    send_forward,
)
from ..sources.weibo import mid2id
from .runtime import (
    GLOBAL_NICKNAME,
    WEIBO_PROXY,
)
from .video import (
    _find_video_duration_seconds,
    _skip_video_for_duration,
)


@weibo.handle()
@resolve_handler
@resolve_controller
async def wb(bot: Bot, event: GroupMessageEvent):
    """解析微博分享链接。"""
    message = get_resolver_message(event)
    weibo_id = None
    reg = r'(jumpUrl|qqdocurl)": ?"(.*?)"'

    # 处理卡片问题
    if "com.tencent.structmsg" in message or "com.tencent.miniapp" in message:
        match = re.search(reg, message)
        logger.debug(f"微博卡片链接匹配结果: {match}")
        if match:
            get_url = match.group(2)
            logger.debug(f"微博卡片展开链接: {get_url}")
            if get_url:
                message = json.loads('"' + get_url + '"')
    # logger.info(message)
    # 判断是否包含 "m.weibo.cn"
    if "m.weibo.cn" in message:
        # https://m.weibo.cn/detail/4976424138313924
        match = re.search(r"(?<=detail/)[A-Za-z\d]+", message) or re.search(
            r"(?<=m.weibo.cn/)[A-Za-z\d]+/[A-Za-z\d]+",
            message,
        )
        weibo_id = match.group(0) if match else None

    # 判断是否包含 "weibo.com/tv/show" 且包含 "mid="
    elif "weibo.com/tv/show" in message and "mid=" in message:
        # https://weibo.com/tv/show/1034:5007449447661594?mid=5007452630158934
        match = re.search(r"(?<=mid=)[A-Za-z\d]+", message)
        if match:
            weibo_id = mid2id(match.group(0))

    # 判断是否包含 "weibo.com"
    elif "weibo.com" in message:
        # https://weibo.com/1707895270/5006106478773472
        match = re.search(r"(?<=weibo.com/)[A-Za-z\d]+/[A-Za-z\d]+", message)
        weibo_id = match.group(0) if match else None

    # 无法获取到id则返回失败信息
    if not weibo_id:
        await weibo.finish(Message("解析失败：无法获取到wb的id"))
    # 最终获取到的 id
    weibo_id = weibo_id.split("/")[1] if "/" in weibo_id else weibo_id
    logger.info(weibo_id)
    # 请求数据
    headers = {
        "accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,image/apng,*/*;q=0.8,"
            "application/signed-exchange;v=b3;q=0.9"
        ),
        "cookie": (
            "_T_WM=40835919903; WEIBOCN_FROM=1110006030; MLOGIN=0; XSRF-TOKEN=4399c8"
        ),
        "Referer": f"https://m.weibo.cn/detail/{weibo_id}",
    } | COMMON_HEADER
    resp = httpx.get(
        WEIBO_SINGLE_INFO.format(weibo_id),
        headers=headers,
        proxy=WEIBO_PROXY,
        timeout=20,
        trust_env=False,
    ).json()
    weibo_data = resp["data"]
    logger.info(weibo_data)
    text, status_title, source, region_name, pics, page_info = (
        weibo_data.get(key)
        for key in [
            "text",
            "status_title",
            "source",
            "region_name",
            "pics",
            "page_info",
        ]
    )
    # 微博说明和图片统一放进同一条合并转发；视频本体仍走统一的视频发送流程。
    weibo_forward_nodes = [
        make_forward_nodes(
            bot.self_id,
            MessageSegment.text(
                f"{GLOBAL_NICKNAME}识别：微博\n"
                f"{re.sub(r'<[^>]+>', '', text or '')}\n"
                f"{status_title or ''}\n{source or ''}\t{region_name or ''}"
            ),
        )
    ]
    links_path = []
    if pics:
        pic_urls = [item["url"] for item in pics]
        image_headers = {"Referer": "http://blog.sina.com.cn/"} | COMMON_HEADER
        download_image_funcs = [
            asyncio.create_task(
                download_image(
                    item,
                    "",
                    WEIBO_PROXY,
                    headers=image_headers,
                )
            )
            for item in pic_urls
        ]
        links_path = await asyncio.gather(*download_image_funcs)
        weibo_forward_nodes.extend(
            make_forward_nodes(
                bot.self_id,
                [
                    MessageSegment.image(file=Path(link).resolve().as_uri())
                    for link in links_path
                ],
            )
        )
    await send_forward(bot, event, weibo_forward_nodes)
    # 清除图片
    for temp in links_path:
        Path(temp).unlink(missing_ok=True)
    if isinstance(page_info, dict):
        urls = page_info.get("urls") or {}
        video_url = urls.get("mp4_720p_mp4", "") or urls.get("mp4_hd_mp4", "")
        if video_url:
            if _skip_video_for_duration(
                "微博",
                _find_video_duration_seconds(page_info),
            ):
                return
            video_headers = {
                "accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "image/avif,image/webp,image/apng,*/*;q=0.8,"
                    "application/signed-exchange;v=b3;q=0.9"
                ),
                "referer": "https://weibo.com/",
            }
            try:
                path = await download_video(
                    video_url,
                    WEIBO_PROXY,
                    ext_headers=video_headers,
                    max_size=media_delivery.video_compress_limit,
                )
            except MediaSizeLimitExceeded as exc:
                logger.warning(f"[微博] 视频超过大小限制，已跳过下载和发送：{exc}")
                return
            except ValueError as exc:
                await weibo.finish(f"视频无法下载：{exc}")
            await send_resolved_video(event, path, WEIBO_PROXY)
