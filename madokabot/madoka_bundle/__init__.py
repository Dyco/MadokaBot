from pathlib import Path

from nonebot import get_driver, load_plugins, logger
from nonebot.plugin import PluginMetadata

from .config import MainConfig
from .db.models import init_madoka_db
from .db.user_source import UserAccount

__plugin_meta__ = PluginMetadata(
    name="圆香聊天机器人",
    description="包含戳一戳、每日签到、商店和聊天等功能的本地插件集合",
    usage="当前包含功能：每日签到、戳一戳、商店、聊天",
    type="application",
    config=MainConfig,
)

driver = get_driver()


@driver.on_startup
async def _():
    try:
        await init_madoka_db()
        await UserAccount.sync_shop_skins()
        logger.info("[Madoka] 数据库和商店资源同步完成")
    except Exception as e:
        logger.error(f"[Madoka] 初始化失败，请检查数据库配置或资源目录: {e}")


inline_plugins_path = str(Path(__file__).parent.joinpath("plugins").resolve())
load_plugins(inline_plugins_path)
