"""Steam 命令入口、帮助与玩家状态查询。"""

import asyncio
import re
from typing import Optional

from nonebot.adapters import Bot
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.log import logger
from nonebot_plugin_alconna import Arparma, At, Image, Match, MsgTarget, UniMessage

from ..client import (
    STEAM_ID_OFFSET,
    get_default_user_data,
    get_steam_users_info,
    get_user_data,
)
from ..config import get_query_proxy, get_steam_api_key
from ..matchers import STEAM_USAGE, steam_cmd
from ..render import draw_friends_status, draw_player_status
from ..state import avatar_path, steam_groups, claim_query_slot
from ..utils import (
    convert_player_name_to_nickname,
    image_to_bytes,
    simplify_steam_player_data,
)


@steam_cmd.handle()
async def check_command_context(target: MsgTarget, result: Arparma):
    """拒绝私聊调用，并为无子命令的请求返回帮助。"""
    if target.private:
        await steam_cmd.finish("暂不支持私聊消息")
    if not result.options:
        await steam_cmd.finish(STEAM_USAGE)


@steam_cmd.assign("help")
async def handle_help():
    """返回 Steam 命令用法。"""
    await steam_cmd.finish(STEAM_USAGE)


@steam_cmd.assign("check")
async def handle_check(target: MsgTarget):
    """查询并绘制当前群已绑定玩家的在线状态。"""
    parent_id = target.parent_id or target.id
    steam_ids = steam_groups.get_steam_ids(parent_id)
    if not steam_ids:
        await steam_cmd.finish("当前群聊未绑定任何 Steam 账号")

    await steam_cmd.send("收到指令，正在尝试读取…")
    try:
        info = await get_steam_users_info(
            steam_ids, get_steam_api_key(), get_query_proxy()
        )
    except Exception as e:
        logger.error(f"Steam API 调用失败: {e}")
        await steam_cmd.finish("无法连接到 Steam API，请检查网络或 API Key")

    if not info.get("response", {}).get("players"):
        await steam_cmd.finish("未查找到玩家信息")

    tasks = [
        simplify_steam_player_data(p, get_query_proxy(), avatar_path)
        for p in info["response"]["players"]
    ]
    try:
        player_results = await asyncio.gather(*tasks)
    except Exception as e:
        logger.exception(f"处理玩家数据时崩溃: {e}")
        await steam_cmd.finish("处理头像数据时出错")

    parent_avatar, parent_name = steam_groups.get_group_profile(parent_id)
    data = [
        convert_player_name_to_nickname(res, parent_id, steam_groups)
        for res in player_results
    ]
    image = draw_friends_status(parent_avatar, parent_name, data)
    await target.send(UniMessage(Image(raw=image_to_bytes(image))))


@steam_cmd.assign("info")
async def handle_info(
    bot: Bot,
    event: GroupMessageEvent,
    target: Match[At | str],
):
    """检查查询冷却并发送指定玩家的资料卡。"""
    parent_id = str(event.group_id)
    sender_id = str(event.user_id)
    steam_id: Optional[str] = None

    if target.available:
        res = target.result
        if isinstance(res, At):
            target_qq = res.target
        else:
            target_qq = "".join(re.findall(r"\d+", res.strip()))
        if not target_qq:
            await steam_cmd.finish("无法识别参数，请输入 QQ 号或 At 某人")
        user_data = steam_groups.get_binding(parent_id, target_qq)
        if not user_data:
            await steam_cmd.finish(f"该用户 ({target_qq}) 尚未在群内绑定 Steam")
        steam_id = user_data["steam_id"]
    else:
        user_data = steam_groups.get_binding(parent_id, sender_id)
        if not user_data:
            await steam_cmd.finish("你尚未绑定 Steam，请使用 `steam bind ID`")
        steam_id = user_data["steam_id"]

    remaining_minutes = claim_query_slot(sender_id)
    if remaining_minutes is not None:
        await steam_cmd.finish(f"频繁查询，{remaining_minutes}分钟后再试。")

    await steam_cmd.send("收到指令，正在尝试读取…")
    try:
        player_data = await get_user_data(steam_id, avatar_path, get_query_proxy())
    except Exception as e:
        logger.exception(f"获取玩家详情失败，使用默认资料继续绘图: {e}")
        player_data = get_default_user_data(steam_id)

    steam_friend_code = str(int(steam_id) - STEAM_ID_OFFSET)
    draw_data = []
    for game in player_data.get("game_data", []):
        try:
            draw_data.append(
                {
                    "game_header": game.get("game_image"),
                    "game_name": game.get("game_name", "未知游戏"),
                    "game_time": f"{game.get('play_time', 0)} 小时",
                    "last_play_time": game.get("last_played", "未知"),
                    "achievements": game.get("achievements", []),
                    "completed_achievement_number": game.get(
                        "completed_achievement_number", 0
                    ),
                    "total_achievement_number": game.get("total_achievement_number", 0),
                }
            )
        except Exception as e:
            logger.warning(f"构建 Steam 游戏绘图数据失败，已跳过该条目: {e}")

    try:
        image = draw_player_status(
            player_data.get("background"),
            player_data.get("avatar"),
            player_data.get("player_name", "Unknown"),
            steam_friend_code,
            player_data.get("description", ""),
            player_data.get("recent_2_week_play_time", "0"),
            draw_data,
            player_data.get("avatar_frame"),
        )
    except Exception as e:
        logger.exception(f"绘制 Steam 详情图失败，改用默认资料重试: {e}")
        fallback_data = get_default_user_data(steam_id)
        try:
            image = draw_player_status(
                fallback_data["background"],
                fallback_data["avatar"],
                player_data.get("player_name", fallback_data["player_name"]),
                steam_friend_code,
                player_data.get("description", fallback_data["description"]),
                None,
                [],
            )
        except Exception as fallback_error:
            logger.exception(f"默认 Steam 详情图绘制仍然失败: {fallback_error}")
            await steam_cmd.finish(
                f"Steam 信息读取完成，但图片渲染失败。\n"
                f"玩家：{player_data.get('player_name', 'Unknown')}\n"
                f"好友代码：{steam_friend_code}"
            )

    try:
        image_bytes = image_to_bytes(image)
    except Exception as image_error:
        logger.exception(f"Steam 详情图转为图片消息失败: {image_error}")
        await steam_cmd.finish(
            f"Steam 信息读取完成，但图片编码失败。\n"
            f"玩家：{player_data.get('player_name', 'Unknown')}\n"
            f"好友代码：{steam_friend_code}"
        )

    await steam_cmd.finish(UniMessage(Image(raw=image_bytes)))
