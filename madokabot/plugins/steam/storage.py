"""群总开关与跨群玩家状态的 JSON 存储。"""

import time
from copy import deepcopy
from typing import Any
from pathlib import Path

from madokabot.core.group.settings import GroupSettingsStore
from madokabot.core.storage.json_store import JsonDataStore

from .monitor_state import mark_group_changed


class SteamGroupStore:
    """只管理公共群数据中 steam 节点的群总开关。"""

    def __init__(self, settings: GroupSettingsStore) -> None:
        """使用共享群存储保存播报开关。"""
        self.settings = settings

    def is_broadcast_enabled(self, group_id: str) -> bool:
        """读取群播报开关，未设置时默认启用。"""
        data = self.settings.get(group_id, "steam", {})
        if not isinstance(data, dict):
            return True
        return bool(data.get("broadcast_enabled", True))

    def set_broadcast_enabled(self, group_id: str, enabled: bool) -> None:
        """保存群总开关。"""
        raw = self.settings.get(group_id, "steam", {})
        data = dict(raw) if isinstance(raw, dict) else {}
        data["broadcast_enabled"] = enabled
        self.settings.set(group_id, "steam", data)
        mark_group_changed(group_id)


class PlayerStatusStore:
    """独立保存跨群共用的玩家状态，避免轮询反复改写群配置。"""

    def __init__(self, save_path: Path) -> None:
        """通过公共 JSON 存储读取按 Steam ID 索引的玩家状态。"""
        self.data_store = JsonDataStore(save_path, {})

    def get_players(self, steam_ids: list[str]) -> list[dict[str, Any]]:
        """返回指定玩家的状态快照，供更新前后比较。"""
        return [
            deepcopy(self.data_store.content[steam_id])
            for steam_id in steam_ids
            if steam_id in self.data_store.content
        ]

    def update_by_players(
        self, players: list[dict[str, Any]], requested_ids: set[str]
    ) -> None:
        """只更新成功返回的玩家；未返回者保留旧快照并标记过期。"""
        updated = deepcopy(self.data_store.content)
        now = int(time.time())
        returned_ids = set()
        for player in players:
            item = dict(player)
            steam_id = item.get("steamid")
            if not steam_id or steam_id not in requested_ids:
                continue
            returned_ids.add(steam_id)
            previous = updated.get(steam_id, {})
            game = item.get("gameextrainfo")
            if game is None:
                item["game_start_time"] = None
            elif game == previous.get("gameextrainfo"):
                item["game_start_time"] = previous.get("game_start_time") or now
            else:
                item["game_start_time"] = now
            item["stale"] = False
            item["last_updated_at"] = now
            updated[steam_id] = item
        for steam_id in requested_ids - returned_ids:
            if steam_id in updated:
                updated[steam_id]["stale"] = True
        if updated != self.data_store.content:
            self.data_store.write(updated)

    @staticmethod
    def compare(
        old_players: list[dict[str, Any]], new_players: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """提取开始、结束和切换游戏的变化，首次遇到的玩家只建立基线。"""
        previous = {item["steamid"]: item for item in old_players}
        changes = []
        for player in new_players:
            old_player = previous.get(player["steamid"])
            if old_player is None or old_player.get("stale") or player.get("stale"):
                continue
            old_game = old_player.get("gameextrainfo")
            new_game = player.get("gameextrainfo")
            if old_game == new_game:
                continue
            change = (
                "start"
                if old_game is None
                else "stop"
                if new_game is None
                else "change"
            )
            changes.append({"type": change, "player": player, "old_player": old_player})
        return changes
