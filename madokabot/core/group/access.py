"""群组访问名单的存储与查询。"""

from enum import IntEnum
from pathlib import Path
from typing import Any

from madokabot.core.resources import ResourceType, ResourceFolder, assets
from madokabot.core.storage.json_store import JsonDataStore

GROUP_ACCESS_PATH = (
    assets.get_dir(ResourceType.JSON, ResourceFolder.GROUP) / "group_access.json"
)
# 白名单和黑名单唯一使用的 JSON 文件路径。

_ACCESS_LIST_NAMES = ("whitelist", "blacklist")


class GroupAccessType(IntEnum):
    """群组访问类型，1 代表白名单，2 代表黑名单。"""

    WHITELIST = 1  # 1：白名单
    BLACKLIST = 2  # 2：黑名单


class GroupAccessStore:
    """管理群组白名单和黑名单。"""

    def __init__(self, save_path: Path = GROUP_ACCESS_PATH) -> None:
        """初始化群组访问名单存储。"""
        self.data_store = JsonDataStore(
            save_path,
            {list_name: [] for list_name in _ACCESS_LIST_NAMES},
        )
        self.content = self._normalize_access(self.data_store.content)

    @staticmethod
    def _normalize_group_id(group_id: str | int) -> str:
        """统一群 ID 格式，并拒绝空值。"""
        value = str(group_id).strip()
        if not value:
            raise ValueError("群 ID 不能为空")
        return value

    @staticmethod
    def _normalize_access_type(access_type: int) -> int:
        """校验访问类型，1 代表白名单，2 代表黑名单。"""
        if isinstance(access_type, bool) or not isinstance(access_type, int):
            raise TypeError("访问类型必须是 1（白名单）或 2（黑名单）")
        if access_type not in {
            GroupAccessType.WHITELIST,
            GroupAccessType.BLACKLIST,
        }:
            raise ValueError("访问类型只能是 1（白名单）或 2（黑名单）")
        return access_type

    @staticmethod
    def _list_name(access_type: int) -> str:
        """将访问类型转换为 JSON 中对应的名单名称。"""
        return "whitelist" if access_type == GroupAccessType.WHITELIST else "blacklist"

    @staticmethod
    def _normalize_access(data: Any) -> dict[str, set[str]]:
        """清洗白名单和黑名单，只保留非空群 ID。"""
        if not isinstance(data, dict):
            data = {}
        return {
            list_name: {
                str(group_id).strip()
                for group_id in data.get(list_name, [])
                if str(group_id).strip()
            }
            if isinstance(data.get(list_name), list)
            else set()
            for list_name in _ACCESS_LIST_NAMES
        }

    def reload(self) -> None:
        """从磁盘重新读取访问名单。"""
        self.data_store.reload()
        self.content = self._normalize_access(self.data_store.content)

    def save(self) -> None:
        """保存访问名单到 group_access.json。"""
        self.data_store.write(
            {
                list_name: sorted(self.content[list_name])
                for list_name in _ACCESS_LIST_NAMES
            }
        )

    def get(self, access_type: int) -> list[str]:
        """获取指定类型的群组列表。"""
        normalized_access_type = self._normalize_access_type(access_type)
        return sorted(self.content[self._list_name(normalized_access_type)])

    def add(self, group_id: str | int, access_type: int) -> bool:
        """将群 ID 写入指定名单，并返回数据是否发生变化。"""
        normalized_group_id = self._normalize_group_id(group_id)
        normalized_access_type = self._normalize_access_type(access_type)
        target_name = self._list_name(normalized_access_type)
        other_name = self._list_name(
            GroupAccessType.BLACKLIST
            if normalized_access_type == GroupAccessType.WHITELIST
            else GroupAccessType.WHITELIST
        )

        changed = normalized_group_id not in self.content[target_name]
        self.content[target_name].add(normalized_group_id)
        if normalized_group_id in self.content[other_name]:
            self.content[other_name].remove(normalized_group_id)
            changed = True
        if not changed:
            return False

        self.save()
        return True

    def remove(self, group_id: str | int) -> bool:
        """从白名单和黑名单移除群 ID，并返回是否实际删除。"""
        normalized_group_id = self._normalize_group_id(group_id)
        changed = False
        for groups in self.content.values():
            if normalized_group_id in groups:
                groups.remove(normalized_group_id)
                changed = True
        if not changed:
            return False

        self.save()
        return True

    def contains(self, group_id: str | int, access_type: int) -> bool:
        """判断群 ID 是否在指定访问名单中。"""
        normalized_group_id = self._normalize_group_id(group_id)
        normalized_access_type = self._normalize_access_type(access_type)
        return (
            normalized_group_id in self.content[self._list_name(normalized_access_type)]
        )

    def is_whitelisted(self, group_id: str | int) -> bool:
        """判断群组是否为白名单。"""
        return self.contains(group_id, GroupAccessType.WHITELIST)

    def is_blacklisted(self, group_id: str | int) -> bool:
        """判断群组是否为黑名单。"""
        return self.contains(group_id, GroupAccessType.BLACKLIST)

    def is_allowed(self, group_id: str | int) -> bool:
        """根据访问名单判断群组是否允许使用机器人功能。"""
        normalized_group_id = self._normalize_group_id(group_id)
        if normalized_group_id in self.content["blacklist"]:
            return False

        whitelist = self.content["whitelist"]
        return not whitelist or normalized_group_id in whitelist


group_access = GroupAccessStore()
# 群组访问名单存储实例，实际数据保存于 group_access.json。


def is_group_whitelisted(group_id: str | int) -> bool:
    """判断群组是否在白名单中。"""

    return group_access.contains(group_id, 1)


def is_group_blacklisted(group_id: str | int) -> bool:
    """判断群组是否在黑名单中。"""

    return group_access.contains(group_id, 2)
