"""kugou 链接解析事件处理器。"""

import json
import os
import re

import httpx
from nonebot import logger
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageSegment

from ..commands import resolve_controller, resolve_handler
from ..constants import (
    COMMON_HEADER,
    KUGOU_TEMP_API,
)
from ..downloads import (
    download_audio,
)
from ..matchers import (
    KUGOU_PATTERN,
)
from ..matchers import (
    kugou_matcher as kg,
)
from ..messages import (
    get_resolver_message,
    make_forward_nodes,
    send_forward,
    upload_file,
)
from .runtime import (
    GLOBAL_NICKNAME,
    KUGOU_PROXY,
)


@kg.handle()
@resolve_handler
@resolve_controller
async def kugou(bot: Bot, event: GroupMessageEvent):
    """提取有效酷狗链接后异步读取歌曲信息，无效卡片直接跳过。"""
    message = get_resolver_message(event)
    if "com.tencent.structmsg" in message:
        card_match = re.search(r'jumpUrl":\s*"([^"]+)"', message)
        if not card_match:
            return
        try:
            message = json.loads('"' + card_match[1] + '"')
        except json.JSONDecodeError:
            return
    url_match = re.search(KUGOU_PATTERN, message, re.IGNORECASE)
    if not url_match:
        return
    url = url_match[0]

    async with httpx.AsyncClient(
        follow_redirects=True,
        proxy=KUGOU_PROXY,
        timeout=20,
        trust_env=False,
    ) as client:
        response = await client.get(url)
    if response.status_code == 200:
        title = response.text
        get_name = r"<title>(.*?)_高音质在线试听"
        name = re.search(get_name, title)
        if name:
            kugou_title = name.group(1)
            async with httpx.AsyncClient(
                headers=COMMON_HEADER,
                proxy=KUGOU_PROXY,
                timeout=20,
                trust_env=False,
            ) as client:
                api_response = await client.get(
                    KUGOU_TEMP_API.replace("{}", kugou_title)
                )
                api_response.raise_for_status()
                kugou_vip_data = api_response.json()
            kugou_url = kugou_vip_data.get("music_url")
            kugou_cover = kugou_vip_data.get("cover")
            kugou_name = kugou_vip_data.get("title")
            kugou_singer = kugou_vip_data.get("singer")
            kugou_music_path = None
            try:
                kugou_music_path = await download_audio(
                    kugou_url,
                    KUGOU_PROXY,
                )
                kugou_forward_nodes = list(
                    make_forward_nodes(
                        bot.self_id,
                        [
                            MessageSegment.image(kugou_cover),
                            MessageSegment.text(
                                f"{GLOBAL_NICKNAME}识别：酷狗音乐\n"
                                f"歌曲：{kugou_name}-{kugou_singer}"
                            ),
                        ],
                    )
                )
                await send_forward(bot, event, kugou_forward_nodes)
                await upload_file(
                    bot,
                    event,
                    kugou_music_path,
                    f"{kugou_name}-{kugou_singer}.{kugou_music_path.split('.')[-1]}",
                )
            except Exception as exc:
                logger.error(f"[Kugou] 音频下载/发送失败: {exc}")
                await send_forward(
                    bot,
                    event,
                    make_forward_nodes(
                        bot.self_id, MessageSegment.text("❌ 音频下载或发送失败。")
                    ),
                )
            finally:
                if kugou_music_path and os.path.exists(kugou_music_path):
                    os.unlink(kugou_music_path)
        else:
            await send_forward(
                bot,
                event,
                make_forward_nodes(
                    bot.self_id,
                    MessageSegment.text(
                        f"{GLOBAL_NICKNAME}\n来源：【酷狗音乐】\n不支持当前外链，请重新分享再试"
                    ),
                ),
            )
    else:
        await send_forward(
            bot,
            event,
            make_forward_nodes(
                bot.self_id,
                MessageSegment.text(
                    f"{GLOBAL_NICKNAME}\n来源：【酷狗音乐】\n获取链接失败"
                ),
            ),
        )
