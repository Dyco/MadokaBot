"""HLTV 赛事插件配置与本地文件路径。"""

from __future__ import annotations

from pathlib import Path

import nonebot_plugin_localstore as store
from nonebot import get_plugin_config
from nonebot.config import Config as NoneBotConfig
from pydantic import Field

from ..madoka_bundle.config import assets
from ..madoka_bundle.constants import ResType, SubFolder


PLUGIN_NAME = "madokabot_cs_match_subscribe"
DATA_DIR = store.get_data_dir(PLUGIN_NAME)
CACHE_DIR = store.get_cache_dir(PLUGIN_NAME)
# 旧版单场订阅文件，仅用于迁移到 hltv_sub.json。
SUBSCRIPTIONS_PATH = store.get_data_file(PLUGIN_NAME, "subscriptions.json")
# HLTV 赛事订阅统一保存于公共 JSON 资源目录。
HLTV_SUB_PATH = assets.get_dir(ResType.JSON, SubFolder.CS) / "hltv_sub.json"
ASSET_DIR = CACHE_DIR / "assets"
PLAYER_BINDINGS_PATH = DATA_DIR / "player_bindings.sqlite3"
PW_SESSION_PATH = store.get_data_file(PLUGIN_NAME, "pw_session.json")


class Config(NoneBotConfig):
    """插件配置。

    HLTV 页面通过 FlareSolverr 获取，目标站点代理默认跟随 MadokaBot 的全局
    proxy 配置；hltv_proxy 仅用于需要单独代理时覆盖它。
    """

    hltv_base_url: str = Field(
        default="https://www.hltv.org",
        description="HLTV 基础地址",
    )
    hltv_proxy: str | None = Field(
        default=None,
        description="HLTV 请求代理；为空时使用 MadokaBot 全局 proxy",
    )
    hltv_flaresolverr_url: str = Field(
        default="http://127.0.0.1:8191/v1",
        description="FlareSolverr API 地址，可填写到 /v1 或服务根地址",
    )
    hltv_flaresolverr_timeout: float = Field(
        default=60.0,
        ge=5.0,
        le=180.0,
        description="FlareSolverr 单次 request.get 的最大等待时间（秒）",
    )
    hltv_flaresolverr_wait_seconds: float = Field(
        default=2.0,
        ge=0.0,
        le=30.0,
        description="FlareSolverr 返回页面前额外等待动态内容的时间（秒）",
    )
    hltv_flaresolverr_retry_attempts: int = Field(
        default=3,
        ge=1,
        le=8,
        description="FlareSolverr 遇到验证页或临时错误时的最大尝试次数",
    )
    hltv_flaresolverr_retry_delay: float = Field(
        default=2.0,
        ge=0.0,
        le=30.0,
        description="FlareSolverr 重试前的等待秒数，按尝试次数递增",
    )
    hltv_flaresolverr_proxy: str | None = Field(
        default=None,
        description="FlareSolverr 访问目标时使用的代理；为空时沿用 hltv_proxy",
    )
    hltv_request_timeout: float = Field(default=25.0, ge=1.0)
    hltv_poll_interval: int = Field(
        default=300,
        ge=30,
        description="订阅比赛轮询间隔（秒）",
    )
    hltv_subscribe_push_each_map: bool = Field(
        default=True,
        description=(
            "赛事订阅是否按地图单独推送开始和结束消息；关闭时按系列赛级别推送"
        ),
    )
    hltv_max_asset_size: int = Field(
        default=5 * 1024 * 1024,
        ge=64 * 1024,
        description="单张赛事资源图片最大大小（字节）",
    )
    cs_rating_width: int = Field(default=810, ge=400)
    cs_rating_device_scale_factor: float = Field(default=2.0, ge=0.5, le=3.0)
    cs_stats_width: int = Field(default=900, ge=600)
    cs_stats_template_2_width: int = Field(
        default=1100,
        ge=700,
        description="暖色横版玩家战绩卡片的渲染宽度",
    )
    cs_pw_session_path: str | None = Field(
        default=None,
        description="完美平台会话文件路径；为空时使用插件数据目录中的 pw_session.json",
    )
    cs_stats_template: int = Field(
        default=1,
        ge=1,
        le=2,
        description="玩家战绩卡片模板版本：1 为默认模板，2 为暖色横版模板",
    )
    cs_pw_api_token: str | None = Field(
        default=None,
        description="完美平台公开战绩接口令牌；为空时使用当前客户端公开令牌",
    )
    cs_pw_api_version: str = Field(
        default="3.7.9.203",
        description="完美平台公开战绩接口使用的客户端版本",
    )
    cs_pw_api_device: str = Field(
        default="rGPSR1772436611LrL5aF8eKG3",
        description="完美平台公开战绩接口使用的客户端设备标识",
    )


config = get_plugin_config(Config)


def ensure_asset_dirs() -> Path:
    """创建资源缓存目录并返回它。"""
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    return ASSET_DIR

