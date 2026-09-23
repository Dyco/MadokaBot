"""初始化公共支持并加载默认功能与扩展插件。"""

from pathlib import Path

from nonebot import load_plugins, require
from nonebot.plugin import PluginMetadata

require("nonebot_plugin_localstore")
require("nonebot_plugin_datastore")
require("nonebot_plugin_apscheduler")
require("nonebot_plugin_alconna")
require("nonebot_plugin_htmlrender")
require("nonebot_plugin_waiter")

from nonebot_plugin_datastore.db import post_db_init  # noqa: E402

from .core.config import CoreConfig  # noqa: E402
from .core.db import init_database  # noqa: E402
from .core.user.schema import migrate_user_schema  # noqa: E402

__plugin_meta__ = PluginMetadata(
    name="圆香聊天机器人",
    description="MadokaBot 默认功能与扩展插件的统一加载入口",
    usage=(
        "基础功能：注册、设置、查询、每日签到、商店、复读、戳一戳、Ping\n"
        "扩展插件：RSS、解析、CS、Steam、制图"
    ),
    type="application",
    config=CoreConfig,
)


@post_db_init
async def _init_database() -> None:
    """在业务模型加载完成、数据库就绪后建表并兼容历史账号字段。"""
    await init_database()
    await migrate_user_schema()


PACKAGE_ROOT = Path(__file__).resolve().parent
load_plugins(str(PACKAGE_ROOT / "default"))
load_plugins(str(PACKAGE_ROOT / "plugins"))
