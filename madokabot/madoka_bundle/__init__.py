from pathlib import Path
from nonebot import get_driver, load_plugins, logger
from nonebot.plugin import PluginMetadata

from .db.models import init_madoka_db
from .config import MainConfig

__plugin_meta__ = PluginMetadata(
    name="樋口円香聊天机器人",
    description="樋口円香聊天机器人，包含戳一戳，每日签到等功能",
    usage="当前包含功能：每日签到、戳一戳",
    type="application",
    config=MainConfig,
)

#初始化数据库
driver = get_driver()

@driver.on_startup
async def _():
    try:
        await init_madoka_db()
        logger.info("[Madoka]数据库初始化完成")
    except Exception as e:
        logger.error(f"[Madoka]数据库初始化失败，请检查数据库配置或文件权限: {e}")

#加载子插件
inline_plugins_path = str(Path(__file__).parent.joinpath("plugins").resolve())
load_plugins(inline_plugins_path)

