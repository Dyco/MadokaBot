"""命令与播报共享的数据实例和查询冷却状态。"""

import math
import time
from typing import Dict, Optional

import nonebot_plugin_localstore as store

from .config import config
from madokabot.core.group.settings import group_settings
from madokabot.core.resources import ResourceFolder, ResourceType, assets
from .storage import PlayerStatusStore, SteamGroupStore

cache_dir = store.get_cache_dir("madokabot_steam")
avatar_path = cache_dir / "player_avatars"
steam_groups = SteamGroupStore(group_settings, cache_dir / "group_avatars")
player_status = PlayerStatusStore(
    assets.get_dir(ResourceType.JSON, ResourceFolder.STEAM) / "player_status.json"
)
_steam_query_timestamps: Dict[str, float] = {}


def claim_query_slot(user_id: str) -> Optional[int]:
    """占用资料查询名额；若仍在冷却中则返回剩余分钟数。"""
    cooldown = config.steam_query_cooldown
    if cooldown <= 0:
        return None

    now = time.monotonic()
    last_query = _steam_query_timestamps.get(user_id)
    if last_query is not None:
        remaining = cooldown - (now - last_query)
        if remaining > 0:
            return math.ceil(remaining / 60)

    _steam_query_timestamps[user_id] = now
    return None
