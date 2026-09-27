"""从公共群资源读取名称与头像。"""

from pathlib import Path

from .settings import group_settings
from madokabot.core.resources import ResourceFolder, ResourceType, assets


def get_group_name(group_id: str | int) -> str:
    """读取公共群昵称，缺失时退回群号。"""
    data = group_settings.get(group_id, "group_info", {})
    name = data.get("group_name") if isinstance(data, dict) else None
    return name if isinstance(name, str) and name.strip() else str(group_id)


def get_group_avatar_path(group_id: str | int) -> Path:
    """返回公共群头像的资源路径。"""
    return assets.get_dir(ResourceType.IMAGE, ResourceFolder.GROUP) / f"{group_id}.png"
