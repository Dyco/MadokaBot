import asyncio

from nonebot import on_metaevent, require
from nonebot.adapters.onebot.v11 import Bot, LifecycleMetaEvent
from nonebot.log import logger
from nonebot.plugin import PluginMetadata

require("nonebot_plugin_apscheduler")
require("nonebot_plugin_localstore")
require("nonebot_plugin_waiter")

from . import command  # noqa: F401  # 注册 RSS 命令
from . import scheduler
from .command.matchers import RSS_USAGE
from .config import DATA_PATH, RSSConfig
from .config import config as plugin_config
from .download import restore_upload_records
from .subscription import Rss
from .utils import send_message_to_admin

VERSION = "2.6.25"

__plugin_meta__ = PluginMetadata(
    name="MadokaRSS",
    description="Madoka机器人RSS订阅插件，订阅源建议选择RSSHub",
    usage=RSS_USAGE,
    type="application",
    homepage="https://github.com/Dyco/MadokaBot",
    config=RSSConfig,
    supported_adapters={"~onebot.v11"},
    extra={"author": "Dyco", "version": VERSION},
)


def check_first_connect(_: LifecycleMetaEvent) -> bool:
    return True


start_metaevent = on_metaevent(rule=check_first_connect, temp=True)


# 启动时发送启动成功信息
@start_metaevent.handle()
async def start(bot: Bot) -> None:
    # 启动后检查 data 目录，不存在就创建
    if not DATA_PATH.is_dir():
        DATA_PATH.mkdir(parents=True, exist_ok=True)

    boot_message = (
        f"Version: v{VERSION}\nAuthor：Dyco(原作者:Quan666)\ngithub.com/Dyco/MadokaBot"
    )

    rss_list = Rss.read_rss()  # 读取list
    if not rss_list:
        await send_message_to_admin(
            f"{plugin_config.first_boot_message}\n{boot_message}", bot
        )
        logger.info(plugin_config.first_boot_message)
    if plugin_config.enable_boot_message:
        await send_message_to_admin(
            f"{plugin_config.boot_success_message}\n{boot_message}", bot
        )
    logger.info(plugin_config.boot_success_message)
    # 创建检查更新任务
    await asyncio.gather(
        *[scheduler.add_job(rss) for rss in rss_list if not rss.stop]
    )
    await restore_upload_records(bot)
