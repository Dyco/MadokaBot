"""HLTV 赛事插件配置与本地文件路径。"""

from __future__ import annotations

from pathlib import Path

import nonebot_plugin_localstore as store
from nonebot import get_plugin_config
from nonebot.config import Config as NoneBotConfig
from pydantic import Field


PLUGIN_NAME = "madokabot_cs_match_subscribe"
DATA_DIR = store.get_data_dir(PLUGIN_NAME)
CACHE_DIR = store.get_cache_dir(PLUGIN_NAME)
SUBSCRIPTIONS_PATH = store.get_data_file(PLUGIN_NAME, "subscriptions.json")
ASSET_DIR = CACHE_DIR / "assets"
PLAYER_BINDINGS_PATH = DATA_DIR / "player_bindings.sqlite3"
PW_SESSION_PATH = DATA_DIR / "pw_session.json"


class Config(NoneBotConfig):
    """插件配置。

    HLTV 访问默认跟随 MadokaBot 的全局 proxy 配置；
    hltv_proxy 仅用于需要单独代理时覆盖它。
    """

    hltv_base_url: str = Field(
        default="https://www.hltv.org",
        description="HLTV 基础地址",
    )
    hltv_proxy: str | None = Field(
        default=None,
        description="HLTV 请求代理；为空时使用 MadokaBot 全局 proxy",
    )
    hltv_request_timeout: float = Field(default=25.0, ge=1.0)
    hltv_poll_interval: int = Field(
        default=90,
        ge=30,
        description="订阅比赛轮询间隔（秒）",
    )
    hltv_max_asset_size: int = Field(
        default=5 * 1024 * 1024,
        ge=64 * 1024,
        description="单张赛事资源图片最大大小（字节）",
    )
    cs_rating_show_player_photos: bool = Field(
        default=False,
        description="是否在 Rating 行中显示选手头像；默认保持 HLTV Rating 页面布局",
    )
    cs_rating_width: int = Field(default=810, ge=400)
    cs_rating_device_scale_factor: float = Field(default=1.0, ge=0.5, le=3.0)
    cs_stats_width: int = Field(default=900, ge=600)
    cs_pw_session_path: str | None = Field(
        default=None,
        description="完美平台会话文件路径；为空时使用插件数据目录中的 pw_session.json",
    )


config = get_plugin_config(Config)


def ensure_asset_dirs() -> Path:
    """创建资源缓存目录并返回它。"""
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    return ASSET_DIR

