from pathlib import Path
from typing import List, Optional

from nonebot import get_plugin_config
from nonebot.config import Config
from nonebot.log import logger
import nonebot_plugin_localstore as store
from pydantic import AnyHttpUrl, SecretStr

try:
    from pydantic import ConfigDict
except ImportError:
    ConfigDict = None

PLUGIN_DATA_NAME = "madokabot_rss_subscription"

DATA_PATH = store.get_data_dir(PLUGIN_DATA_NAME)
JSON_PATH = store.get_data_file(PLUGIN_DATA_NAME, "rss.json")
CACHE_DB_PATH = store.get_data_file(PLUGIN_DATA_NAME, "cache.db")
DOWNLOAD_RECORD_PATH = store.get_data_file(
    PLUGIN_DATA_NAME, "download_records.json"
)

LEGACY_DATA_PATH = Path.cwd() / "data"
LEGACY_JSON_PATH = LEGACY_DATA_PATH / "rss.json"


class RSSConfig(Config):
    if ConfigDict is not None:
        model_config = ConfigDict(extra="allow")
    else:

        class Config:
            extra = "allow"
    rss_proxy: Optional[str] = None
    rsshub: AnyHttpUrl = "https://rsshub.app"  # type: ignore
    rsshub_backup: List[AnyHttpUrl] = []
    db_cache_expire: int = 30
    limit: int = 200
    max_length: int = 1024
    debug: bool = (
        False
    )
    rss_auto_forward: bool = True

    zip_size: int = 2 * 1024
    gif_zip_size: int = 6 * 1024
    img_format: Optional[str] = None
    img_down_path: Optional[str] = None

    blockquote: bool = True
    black_word: Optional[List[str]] = None

    danbooru_user_id: Optional[int] = None
    danbooru_login: Optional[str] = None
    danbooru_api_key: Optional[SecretStr] = None

    aria2_rpc_url: str = "http://127.0.0.1:6800/jsonrpc"
    aria2_rpc_secret: Optional[str] = None
    aria2_download_path: Optional[str] = (
        None  # 使用机器人可访问的本地目录
    )
    aria2_acquire_timeout: int = 60 # 单位：秒
    aria2_max_file_size_mb: int = 512 # 单位：MiB
    aria2_max_total_size_mb: int = 1024 # 单位：MiB
    rss_upload_verify_delay: int = 3600 # 单位：秒
    rss_upload_concurrency: int = 1
    down_status_msg_group: Optional[List[int]] = None
    down_status_msg_date: int = 90 # 单位：秒
    down_status_msg_recall_delay: int = 60 # 单位：秒

    telegram_admin_ids: List[int] = []
    telegram_bot_token: Optional[str] = None


config = get_plugin_config(RSSConfig)
logger.debug(f"RSS Config loaded: {config!r}")
