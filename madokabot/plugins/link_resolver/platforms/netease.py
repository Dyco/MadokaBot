"""netease 链接解析事件处理器。"""

import os
import re

import httpx
from nonebot import logger
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageSegment

from ..commands import resolve_controller, resolve_handler
from ..constants import (
    COMMON_HEADER,
    NETEASE_TEMP_API,
    NETEASE_TEMP_API_FALLBACK,
)
from ..downloads import (
    download_audio,
)
from ..matchers import (
    netease_matcher as ncm,
)
from ..messages import (
    get_resolver_message,
    make_forward_nodes,
    send_forward,
    upload_file,
)
from .runtime import (
    GLOBAL_NICKNAME,
    NETEASE_PROXY,
)


@ncm.handle()
@resolve_handler
@resolve_controller
async def netease(bot: Bot, event: GroupMessageEvent):
    """解析网易云音乐分享链接。"""
    message = get_resolver_message(event)
    # 识别短链接
    if "163cn.tv" in message:
        try:
            short_url = re.search(
                r"(http:|https:)\/\/163cn\.tv\/([a-zA-Z0-9]+)", message
            ).group(0)
            async with httpx.AsyncClient(
                proxy=NETEASE_PROXY,
                timeout=20,
                trust_env=False,
            ) as client:
                head_resp = await client.head(short_url, follow_redirects=True)
            message = str(head_resp.url)
        except Exception as e:
            logger.error(f"[NCM] 短链解析失败: {e}")
            await ncm.finish(Message(f"❌ {GLOBAL_NICKNAME}无法解析此网易云短链接。"))

    match = re.search(r"id=(\d+)", message)
    if not match:
        await ncm.finish(Message(f"❌ {GLOBAL_NICKNAME}未能在链接中找到歌曲 ID。"))

    ncm_id = match.group(1)
    logger.info(f"[NCM] 歌曲 ID: {ncm_id}")

    api_candidates = [
        ("main", NETEASE_TEMP_API.replace("{}", ncm_id)),
        ("fallback", NETEASE_TEMP_API_FALLBACK.replace("{}", ncm_id)),
    ]

    ncm_url = None
    ncm_cover = None
    ncm_singer = "未知歌手"
    ncm_title = f"网易云歌曲_{ncm_id}"
    last_error = None

    for api_name, api_url in api_candidates:
        try:
            async with httpx.AsyncClient(
                proxy=NETEASE_PROXY,
                timeout=15,
                trust_env=False,
            ) as client:
                response = await client.get(api_url, headers=COMMON_HEADER)
            logger.debug(
                f"[NCM][{api_name}] 接口状态: {response.status_code} | 内容: {response.text}"
            )

            if response.status_code != 200:
                last_error = f"HTTP {response.status_code}"
                logger.warning(
                    f"[NCM][{api_name}] 接口状态异常: {response.status_code}"
                )
                continue

            resp_json = response.json()

            if api_name == "main":
                if resp_json.get("code") != 0:
                    last_error = resp_json.get("message", "未知错误")
                    logger.warning(f"[NCM][{api_name}] 接口返回错误: {last_error}")
                    continue

                data_list = resp_json.get("data")
                if not isinstance(data_list, list) or not data_list:
                    last_error = "接口未返回有效歌曲数据"
                    logger.warning(
                        f"[NCM][{api_name}] 接口未返回有效 data: {resp_json}"
                    )
                    continue

                song_data = data_list[0]
                singers = song_data.get("singers") or []
                singer_names = [
                    singer.get("name")
                    for singer in singers
                    if isinstance(singer, dict) and singer.get("name")
                ]

                ncm_url = song_data.get("url")
                ncm_cover = song_data.get("picurl")
                ncm_singer = " / ".join(singer_names) if singer_names else "未知歌手"
                ncm_title = song_data.get("name") or f"网易云歌曲_{ncm_id}"
            else:
                if resp_json.get("status") != 200:
                    last_error = resp_json.get("msg", "未知错误")
                    logger.warning(f"[NCM][{api_name}] 接口返回错误: {last_error}")
                    continue

                ncm_url = resp_json.get("url")
                ncm_cover = resp_json.get("pic")
                ncm_singer = resp_json.get("ar_name") or "未知歌手"
                ncm_title = resp_json.get("name") or f"网易云歌曲_{ncm_id}"

            if ncm_url:
                logger.info(f"[NCM] 使用 {api_name} 接口解析成功")
                break

            last_error = "未获取到播放链接"
            logger.warning(f"[NCM][{api_name}] 接口未返回播放链接: {resp_json}")
        except Exception as e:
            last_error = str(e)
            logger.error(f"[NCM][{api_name}] 接口请求失败: {e}")

    if not ncm_url:
        await ncm.finish(
            f"❌ 未获取到播放链接，主备接口均失败：{last_error or '未知错误'}"
        )
        return

    ncm_music_path = None
    try:
        ncm_music_path = await download_audio(ncm_url, NETEASE_PROXY)
        ncm_forward_nodes = list(
            make_forward_nodes(
                bot.self_id,
                [
                    MessageSegment.image(ncm_cover),
                    MessageSegment.text(
                        f"{GLOBAL_NICKNAME}识别：网易云音乐\n"
                        f"歌名：{ncm_title} - {ncm_singer}"
                    ),
                ],
            )
        )
        await send_forward(bot, event, ncm_forward_nodes)
        await upload_file(
            bot,
            event,
            ncm_music_path,
            f"{ncm_title}-{ncm_singer}.{ncm_music_path.split('.')[-1]}",
        )
    except Exception as e:
        logger.error(f"[NCM] 音频下载/发送失败: {e}")
        await send_forward(
            bot,
            event,
            make_forward_nodes(
                bot.self_id, MessageSegment.text("❌ 音频下载或发送失败。")
            ),
        )
    finally:
        if ncm_music_path and os.path.exists(ncm_music_path):
            os.unlink(ncm_music_path)
