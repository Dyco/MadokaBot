from typing import Optional

from nonebot import get_plugin_config
from pydantic import BaseModel, Field

from madokabot.core.config import config as madoka_config


class SteamConfig(BaseModel):
    """Steam 查询、播报和冷却配置。"""

    steam_api_key: str
    steam_request_interval: int = 60
    steam_batch_size: int = Field(default=25, ge=1, le=100)
    steam_broadcast_type: str = "part"
    steam_disable_broadcast_on_startup: bool = False
    steam_command_priority: int = 10
    steam_query_use_proxy: bool = True
    steam_monitor_use_proxy: bool = False
    steam_query_cooldown: int = 600


config = get_plugin_config(SteamConfig)


def get_steam_api_key() -> str:
    """读取并去除 Steam API 密钥两端空白。"""
    return config.steam_api_key.strip()


def _get_configured_proxy(enabled: bool) -> Optional[str]:
    """根据功能开关读取并规范全局代理地址。"""
    if not enabled or not madoka_config.proxy:
        return None
    proxy = str(madoka_config.proxy).strip()
    if not proxy:
        return None
    return proxy if "://" in proxy else f"http://{proxy}"


def get_query_proxy() -> Optional[str]:
    """读取主动查询使用的代理。"""
    return _get_configured_proxy(config.steam_query_use_proxy)


def get_monitor_proxy() -> Optional[str]:
    """读取定时播报使用的代理。"""
    return _get_configured_proxy(config.steam_monitor_use_proxy)
