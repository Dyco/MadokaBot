from pathlib import Path
from typing import List, Optional

from nonebot import get_plugin_config
from nonebot.config import Config
from nonebot.log import logger
import nonebot_plugin_localstore as store
from pydantic import AnyHttpUrl, Field

try:
    from pydantic import ConfigDict
except ImportError:  # pydantic v1 compatibility
    ConfigDict = None

PLUGIN_DATA_NAME = "madokabot_rss_subscription"

# ELF_RSS originally stored all state in ``Path.cwd() / "data"``.  MadokaBot
# already centralises local plugin data through nonebot-plugin-localstore, so
# keep the same file layout while placing it in the configured data directory.
DATA_PATH = store.get_data_dir(PLUGIN_DATA_NAME)
JSON_PATH = store.get_data_file(PLUGIN_DATA_NAME, "rss.json")
CACHE_DB_PATH = store.get_data_file(PLUGIN_DATA_NAME, "cache.db")

# Used only as a read-only migration source for an older standalone ELF_RSS
# installation.  New writes always go to LocalStore.
LEGACY_DATA_PATH = Path.cwd() / "data"
LEGACY_JSON_PATH = LEGACY_DATA_PATH / "rss.json"


class RSSConfig(Config):
    if ConfigDict is not None:
        model_config = ConfigDict(extra="allow")
    else:

        class Config:
            extra = "allow"

    # 代理地址
    # ``rss_proxy`` is kept for backwards-compatible configuration loading.
    # Runtime requests prefer MadokaBot's shared PROXY setting; see
    # utils.get_proxy().
    rss_proxy: Optional[str] = None
    rsshub: AnyHttpUrl = "https://rsshub.app"  # type: ignore
    # 备用 rsshub 地址
    rsshub_backup: List[AnyHttpUrl] = Field(default_factory=list)
    db_cache_expire: int = 30
    limit: int = 200
    max_length: int = 1024  # 正文长度限制，防止消息太长刷屏，以及消息过长发送失败的情况
    enable_boot_message: bool = True  # 是否启用启动时的提示消息推送
    # 首次启动且没有任何订阅时发送的提示消息
    first_boot_message: str = (
        "首次启动，目前没有订阅，请添加！\n另外，请检查配置文件的内容（详见部署教程）！"
    )
    # 启动成功时发送的提示消息
    boot_success_message: str = "Madoka机器人订阅器启动成功！"
    debug: bool = (
        False  # 是否开启 debug 模式，开启后会打印更多的日志信息，同时检查更新时不会使用缓存,便于调试
    )

    zip_size: int = 2 * 1024
    gif_zip_size: int = 6 * 1024
    img_format: Optional[str] = None
    img_down_path: Optional[str] = None

    blockquote: bool = True
    black_word: Optional[List[str]] = None

    aria2_rpc_url: str = "http://127.0.0.1:6800/jsonrpc"  # aria2 JSON-RPC 地址
    aria2_rpc_secret: Optional[str] = None  # aria2 RPC 密钥
    aria2_download_path: Optional[str] = (
        None  # aria2 下载目录，必须是 MadokaBot 能访问到的本地路径
    )
    aria2_acquire_timeout: int = Field(
        default=60,
        gt=0,
        description="下载链接、种子文件及磁力元数据的获取超时，单位秒",
    )
    aria2_file_cleanup_delay: int = Field(
        default=3600,
        ge=0,
        description="下载文件的自动清理延迟，单位秒；设为 0 时关闭",
    )
    aria2_max_file_size_mb: int = Field(
        default=2048,
        gt=0,
        description="单个下载文件的大小上限，单位 MiB",
    )
    aria2_max_total_size_mb: int = Field(
        default=4096,
        gt=0,
        description="单个下载任务的总文件大小上限，单位 MiB",
    )
    down_status_msg_group: Optional[List[int]] = None  # 下载进度消息提示群组
    down_status_msg_date: int = 10  # 下载进度检查及提示间隔时间，单位秒

    telegram_admin_ids: List[int] = Field(
        default_factory=list
    )  # Telegram 管理员 ID 列表，用于接收离线通知和管理机器人
    telegram_bot_token: Optional[str] = None  # Telegram 机器人的 token


config = get_plugin_config(RSSConfig)
logger.debug(f"RSS Config loaded: {config!r}")
