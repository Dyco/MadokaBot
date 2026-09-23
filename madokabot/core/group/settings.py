# -*- coding: utf-8 -*-
"""群组插件配置的 JSON 存储。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from madokabot.core.resources import ResourceType, ResourceFolder, assets
from madokabot.core.storage.json_store import JsonData, JsonDataStore

GROUP_SETTINGS_PATH = (
    assets.get_dir(ResourceType.JSON, ResourceFolder.GROUP) / "group_set.json"
)
# 群组插件配置唯一使用的 JSON 文件路径。


class GroupSettingsStore:
    """管理群组与插件配置之间的映射。"""

    def __init__(self, save_path: Path = GROUP_SETTINGS_PATH) -> None:
        """初始化群组配置存储。"""
        self.data_store = JsonDataStore(save_path, {})
        self.content = self._normalize_groups(self.data_store.content)

    @staticmethod
    def _normalize_group_id(group_id: str | int) -> str:
        """统一群 ID 格式，并拒绝空值。"""
        value = str(group_id).strip()
        if not value:
            raise ValueError("群 ID 不能为空")
        return value

    @staticmethod
    def _normalize_plugin_name(plugin_name: str) -> str:
        """统一插件名格式，并拒绝空值。"""
        value = plugin_name.strip()
        if not value:
            raise ValueError("插件名不能为空")
        return value

    @staticmethod
    def _normalize_groups(data: Any) -> dict[str, dict[str, JsonData]]:
        """清洗群组配置，只保留 JSON 对象或数组。"""
        if not isinstance(data, dict):
            return {}
        return {
            str(group_id): {
                str(plugin_name): value
                for plugin_name, value in plugin_data.items()
                if isinstance(value, (dict, list))
            }
            for group_id, plugin_data in data.items()
            if isinstance(plugin_data, dict)
        }

    def reload(self) -> None:
        """从磁盘重新读取群组配置。"""
        self.data_store.reload()
        self.content = self._normalize_groups(self.data_store.content)

    def save(self) -> None:
        """保存群组配置到 group_set.json。"""
        self.data_store.write(self.content)

    def get(
        self,
        group_id: str | int,
        plugin_name: str,
        default: JsonData | None = None,
    ) -> JsonData | None:
        """读取指定群组的指定插件配置。"""
        normalized_group_id = self._normalize_group_id(group_id)
        normalized_plugin_name = self._normalize_plugin_name(plugin_name)
        return self.content.get(normalized_group_id, {}).get(
            normalized_plugin_name,
            default,
        )

    def get_all(self, plugin_name: str) -> dict[str, JsonData]:
        """读取指定插件保存的全部群组配置。"""
        normalized_plugin_name = self._normalize_plugin_name(plugin_name)
        return {
            group_id: plugin_data[normalized_plugin_name]
            for group_id, plugin_data in self.content.items()
            if normalized_plugin_name in plugin_data
        }

    def set(
        self,
        group_id: str | int,
        plugin_name: str,
        data: JsonData,
    ) -> None:
        """写入指定群组的插件配置，并立即持久化。"""
        if not isinstance(data, (dict, list)):
            raise TypeError("插件配置必须是 JSON 对象或数组")

        normalized_group_id = self._normalize_group_id(group_id)
        normalized_plugin_name = self._normalize_plugin_name(plugin_name)
        self.content.setdefault(normalized_group_id, {})[normalized_plugin_name] = data
        self.save()

    def remove(self, group_id: str | int, plugin_name: str) -> bool:
        """删除指定群组的插件配置，并返回是否实际删除。"""
        normalized_group_id = self._normalize_group_id(group_id)
        normalized_plugin_name = self._normalize_plugin_name(plugin_name)
        group_config = self.content.get(normalized_group_id)
        if group_config is None or normalized_plugin_name not in group_config:
            return False

        del group_config[normalized_plugin_name]
        if not group_config:
            del self.content[normalized_group_id]
        self.save()
        return True


group_settings = GroupSettingsStore()
# 通用群组配置存储实例，插件只需传入群 ID 和插件名即可使用。


__all__ = ["GROUP_SETTINGS_PATH", "GroupSettingsStore", "group_settings"]
