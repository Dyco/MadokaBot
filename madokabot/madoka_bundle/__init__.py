from pathlib import Path

from nonebot import load_plugins
from nonebot.plugin import PluginMetadata
from nonebot_plugin_datastore.db import post_db_init

from .config import MainConfig
from .db.models import init_madoka_db

__plugin_meta__ = PluginMetadata(
    name="圆香聊天机器人",
    description="包含戳一戳、每日签到、商店和聊天等功能的本地插件集合",
    usage="当前包含功能：每日签到、戳一戳、商店、聊天",
    type="application",
    config=MainConfig,
)


@post_db_init
async def _init_database():
    await init_madoka_db()


inline_plugins_path = str((Path(__file__).parent / "plugins").resolve())
load_plugins(inline_plugins_path)
