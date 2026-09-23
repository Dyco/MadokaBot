"""Steam 在线状态更新与游戏动态播报。"""

import time
from typing import Dict, List

import nonebot
from PIL import Image as PILImage
from nonebot.log import logger
from nonebot_plugin_alconna import Image, Target, Text, UniMessage

from .client import STEAM_USER_CACHE_TTL, get_steam_users_info_cached
from .config import config, get_monitor_proxy, get_steam_api_key
from .models import ProcessedPlayer
from .render import draw_start_gaming, vertically_concatenate_images
from .state import avatar_path, steam_groups, player_status
from .utils import fetch_avatar, image_to_bytes


async def update_steam_info():
    """批量刷新已绑定玩家的状态，并返回各群刷新前的快照。"""
    bind_map = steam_groups.get_bindings_by_group()
    steam_ids = {steam_id for ids in bind_map.values() for steam_id in ids}

    steam_info = await get_steam_users_info_cached(
        list(steam_ids),
        get_steam_api_key(),
        get_monitor_proxy(),
        STEAM_USER_CACHE_TTL,
    )

    old = {pid: player_status.get_players(ids) for pid, ids in bind_map.items()}

    if steam_info["response"]["players"]:
        player_status.update_by_players(steam_info["response"]["players"])

    return old


async def broadcast_steam_info(
    parent_id: str,
    old_players: List[ProcessedPlayer],
    new_players: List[ProcessedPlayer],
):
    """比较玩家状态变化并向启用播报的群发送游戏动态。"""
    if not steam_groups.is_broadcast_enabled(parent_id):
        return None

    play_data = player_status.compare(old_players, new_players)
    msg = []

    for entry in play_data:
        player = entry["player"]
        old_player = entry.get("old_player")

        if entry["type"] == "start":
            msg.append(f"{player['personaname']} 开始玩 {player['gameextrainfo']} 了")
        elif entry["type"] in ("stop", "change"):
            time_start = old_player["game_start_time"]
            time_stop = time.time()
            hours = int((time_stop - time_start) / 3600)
            minutes = int((time_stop - time_start) % 3600 / 60)
            time_str = (
                f"{hours} 小时 {minutes} 分钟" if hours > 0 else f"{minutes} 分钟"
            )

            if entry["type"] == "change":
                msg.append(
                    f"{player['personaname']} 玩了 {time_str} "
                    f"{old_player['gameextrainfo']} 后，开始玩 {player['gameextrainfo']} 了"
                )
            else:
                msg.append(
                    f"{player['personaname']} 玩了 {time_str} "
                    f"{old_player['gameextrainfo']} 后不玩了"
                )

    if not msg:
        return None

    if config.steam_broadcast_type == "part":
        avatar_cache: Dict[str, PILImage.Image] = {}
        images = []

        for entry in play_data:
            if entry["type"] not in ("start", "change"):
                continue

            steamid = entry["player"]["steamid"]
            if steamid in avatar_cache:
                avatar = avatar_cache[steamid]
            else:
                avatar = await fetch_avatar(
                    entry["player"],
                    avatar_path,
                    get_monitor_proxy(),
                )
                avatar_cache[steamid] = avatar

            bind_info = steam_groups.get_binding_by_steam_id(parent_id, steamid) or {}
            img = draw_start_gaming(
                avatar,
                entry["player"]["personaname"],
                entry["player"]["gameextrainfo"],
                bind_info.get("nickname"),
            )
            images.append(img)

        if images:
            image = (
                vertically_concatenate_images(images) if len(images) > 1 else images[0]
            )
            uni_msg = UniMessage(
                [Text("\n".join(msg)), Image(raw=image_to_bytes(image))]
            )
        else:
            uni_msg = UniMessage([Text("\n".join(msg))])
    elif config.steam_broadcast_type == "none":
        uni_msg = UniMessage([Text("\n".join(msg))])
    else:
        logger.error(f"未知的播报类型: {config.steam_broadcast_type}")
        return None

    bots = list(nonebot.get_bots().values())
    if not bots:
        logger.warning("Steam 自动播报跳过：当前没有可用的 Bot 连接")
        return None

    bot = bots[0]
    try:
        await uni_msg.send(
            Target(parent_id, parent_id, True, False, "", bot.adapter.get_name()),
            bot,
        )
    except Exception as e:
        logger.error(f"Steam 自动播报发送失败: parent_id={parent_id}, error={e}")
        return None
