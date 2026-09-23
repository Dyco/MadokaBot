"""通过公共群数据和 JSON 存储管理 Steam 数据。"""

import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from PIL import Image

from madokabot.core.group.settings import GroupSettingsStore
from madokabot.core.storage.json_store import JsonDataStore
from .constants import unknown_avatar_path


class SteamGroupStore:
    """管理各群 steam 节点内的绑定、备注、群资料和播报开关。"""

    def __init__(self, settings: GroupSettingsStore, avatar_dir: Path) -> None:
        """使用共享群存储和独立的群头像缓存目录。"""
        self.settings = settings
        self.avatar_dir = avatar_dir

    def _get(self, group_id: str) -> dict[str, Any]:
        """读取群 Steam 数据副本，避免未保存的修改影响共享状态。"""
        return deepcopy(self.settings.get(group_id, "steam", {}))

    def list_bindings(self, group_id: str) -> list[dict[str, Any]]:
        """返回当前群的绑定记录副本。"""
        return self._get(group_id).get("bindings", [])

    def get_binding(self, group_id: str, user_id: str) -> dict[str, Any] | None:
        """读取指定群成员的 Steam 绑定。"""
        return next(
            (
                item
                for item in self.list_bindings(group_id)
                if item["user_id"] == user_id
            ),
            None,
        )

    def get_binding_by_steam_id(
        self, group_id: str, steam_id: str
    ) -> dict[str, Any] | None:
        """读取当前群内使用指定 Steam 账号的绑定。"""
        return next(
            (
                item
                for item in self.list_bindings(group_id)
                if item["steam_id"] == steam_id
            ),
            None,
        )

    def bind(self, group_id: str, user_id: str, steam_id: str) -> None:
        """保存绑定并保留备注，拒绝同一群内不同成员占用同一账号。"""
        data = self._get(group_id)
        bindings = data.setdefault("bindings", [])
        for item in bindings:
            if item["steam_id"] == steam_id and item["user_id"] != user_id:
                raise ValueError(f"该 Steam ID 已被群成员 {item['user_id']} 占用")
        existing = next((item for item in bindings if item["user_id"] == user_id), None)
        if existing is None:
            bindings.append(
                {"user_id": user_id, "steam_id": steam_id, "nickname": None}
            )
        else:
            existing["steam_id"] = steam_id
        self.settings.set(group_id, "steam", data)

    def unbind(self, group_id: str, user_id: str) -> bool:
        """删除群成员绑定并保存，未绑定时返回否。"""
        data = self._get(group_id)
        bindings = data.get("bindings", [])
        remaining = [item for item in bindings if item["user_id"] != user_id]
        if len(remaining) == len(bindings):
            return False
        data["bindings"] = remaining
        self.settings.set(group_id, "steam", data)
        return True

    def set_nickname(self, group_id: str, user_id: str, nickname: str | None) -> bool:
        """保存或清除绑定昵称，未绑定时返回否。"""
        data = self._get(group_id)
        for item in data.get("bindings", []):
            if item["user_id"] == user_id:
                item["nickname"] = nickname
                self.settings.set(group_id, "steam", data)
                return True
        return False

    def get_steam_ids(self, group_id: str) -> list[str]:
        """返回当前群绑定的 Steam 账号列表。"""
        return [item["steam_id"] for item in self.list_bindings(group_id)]

    def get_bindings_by_group(self) -> dict[str, list[str]]:
        """返回有绑定记录的群及其 Steam 账号，供统一轮询使用。"""
        return {
            group_id: [item["steam_id"] for item in data["bindings"]]
            for group_id, data in self.settings.get_all("steam").items()
            if data.get("bindings")
        }

    def is_broadcast_enabled(self, group_id: str) -> bool:
        """读取群播报开关，未设置时默认启用。"""
        return self._get(group_id).get("broadcast_enabled", True)

    def set_broadcast_enabled(self, group_id: str, enabled: bool) -> None:
        """保存群播报开关，保留绑定和群资料。"""
        data = self._get(group_id)
        data["broadcast_enabled"] = enabled
        self.settings.set(group_id, "steam", data)

    def update_group_profile(
        self, group_id: str, avatar: Image.Image, name: str
    ) -> None:
        """缓存群头像，并将群名写入共享群数据。"""
        self.avatar_dir.mkdir(parents=True, exist_ok=True)
        avatar.save(self.avatar_dir / f"{group_id}.png")
        data = self._get(group_id)
        data["group_name"] = name
        self.settings.set(group_id, "steam", data)

    def get_group_profile(self, group_id: str) -> tuple[Image.Image, str]:
        """读取群资料；头像缓存缺失时使用默认头像。"""
        path = self.avatar_dir / f"{group_id}.png"
        with Image.open(path if path.is_file() else unknown_avatar_path) as avatar:
            return avatar.copy(), self._get(group_id).get("group_name") or group_id


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

    def update_by_players(self, players: list[dict[str, Any]]) -> None:
        """更新在线状态和游戏开始时间，并使用公共方法持久化。"""
        updated = {}
        now = int(time.time())
        for player in players:
            item = dict(player)
            previous = self.data_store.content.get(item["steamid"], {})
            game = item.get("gameextrainfo")
            if game is None:
                item["game_start_time"] = None
            elif game == previous.get("gameextrainfo"):
                item["game_start_time"] = previous["game_start_time"]
            else:
                item["game_start_time"] = now
            updated[item["steamid"]] = item
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
            if old_player is None:
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
