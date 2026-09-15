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
from .download import restore_upload_records
from .subscription import Rss

VERSION = "2.6.25"

__plugin_meta__ = PluginMetadata(
    name="MadokaRSS",
    description="Madoka机器人RSS订阅插件，主指令为RSS",
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

    rss_list = Rss.read_rss()  # 读取list
    # 上传恢复不依赖任何订阅源，优先执行，避免单个源初始化失败时
    # 连带阻断重启后的上传与核验任务。
    try:
        await restore_upload_records(bot)
    except Exception:
        logger.exception("恢复 RSS 上传记录失败")

    active_rss = [rss for rss in rss_list if not rss.stop]
    jobs = [scheduler.add_job(rss) for rss in active_rss]
    if jobs:
        results = await asyncio.gather(*jobs, return_exceptions=True)
        for rss, result in zip(active_rss, results):
            if isinstance(result, BaseException):
                logger.error(f"初始化订阅任务[{rss.name}]失败：{result}")
