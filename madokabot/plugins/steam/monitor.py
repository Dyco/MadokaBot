"""Steam 在线状态更新与游戏动态播报。"""

import time
from typing import Dict, List

import nonebot
from PIL import Image as PILImage
from nonebot.log import logger
from nonebot_plugin_alconna import Image, Target, Text, UniMessage

from .client import STEAM_USER_CACHE_TTL, get_steam_users_info_cached
from .bindings import list_active_bindings_by_group, list_group_bindings
from .config import config, get_monitor_proxy, get_steam_api_key
from .models import ProcessedPlayer
from .monitor_state import get_monitor_version
from .render import draw_start_gaming, vertically_concatenate_images
from .state import avatar_path, steam_groups, player_status
from .utils import fetch_avatar, image_to_bytes

_monitored_targets: dict[tuple[str, str, str], tuple[int, int]] = {}


async def update_steam_info():
    """按有效订阅去重轮询，并为新启用的群订阅建立状态基线。"""
    global _monitored_targets

    bind_map = {
        group_id: bindings
        for group_id, bindings in (await list_active_bindings_by_group()).items()
        if steam_groups.is_broadcast_enabled(group_id)
    }
    target_versions = {
        (group_id, binding["user_id"], binding["steam_id"]): get_monitor_version(
            group_id, binding["user_id"]
        )
        for group_id, bindings in bind_map.items()
        for binding in bindings
    }
    steam_ids = {steam_id for _, _, steam_id in target_versions}
    if not steam_ids:
        _monitored_targets = {}
        return {}

    old = {}
    for group_id, bindings in bind_map.items():
        stable_ids = {
            binding["steam_id"]
            for binding in bindings
            if _monitored_targets.get(
                (group_id, binding["user_id"], binding["steam_id"])
            )
            == target_versions[
                (group_id, binding["user_id"], binding["steam_id"])
            ]
        }
        old[group_id] = player_status.get_players(sorted(stable_ids))

    try:
        steam_info = await get_steam_users_info_cached(
            sorted(steam_ids),
            get_steam_api_key(),
            get_monitor_proxy(),
            STEAM_USER_CACHE_TTL,
        )
        players = steam_info.get("response", {}).get("players", [])
    except Exception:
        logger.exception("Steam 状态轮询失败，保留旧快照")
        players = []
    player_status.update_by_players(players, steam_ids)
    _monitored_targets = target_versions

    return {
        group_id: (
            old[group_id],
            player_status.get_players([item["steam_id"] for item in bindings]),
            target_versions,
        )
        for group_id, bindings in bind_map.items()
    }


async def broadcast_steam_info(
    parent_id: str,
    old_players: List[ProcessedPlayer],
    new_players: List[ProcessedPlayer],
    target_versions: dict[tuple[str, str, str], tuple[int, int]],
):
    """只向仍启用播报的群发送当前订阅玩家的游戏动态。"""
    if not steam_groups.is_broadcast_enabled(parent_id):
        return None

    bindings = [
        binding
        for binding in await list_group_bindings(parent_id)
        if binding["enabled"]
        and target_versions.get(
            (parent_id, binding["user_id"], binding["steam_id"])
        )
        == get_monitor_version(parent_id, binding["user_id"])
    ]
    active_ids = {binding["steam_id"] for binding in bindings}
    play_data = [
        item
        for item in player_status.compare(old_players, new_players)
        if item["player"]["steamid"] in active_ids
    ]
    msg = []

    for entry in play_data:
        player = entry["player"]
        old_player = entry.get("old_player")

        if entry["type"] == "start":
            msg.append(f"{player['personaname']} 开始玩 {player['gameextrainfo']} 了")
        elif entry["type"] in ("stop", "change"):
            time_start = old_player.get("game_start_time") or time.time()
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

            bind_info = next(
                (item for item in bindings if item["steam_id"] == steamid), {}
            )
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
