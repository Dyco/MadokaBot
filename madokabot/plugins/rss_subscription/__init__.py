import asyncio

from nonebot import on_metaevent, require
from nonebot.adapters.onebot.v11 import Bot, LifecycleMetaEvent
from nonebot.log import logger
from nonebot.plugin import PluginMetadata

require("nonebot_plugin_apscheduler")
require("nonebot_plugin_localstore")
require("nonebot_plugin_waiter")

from . import commands as commands  # noqa: E402,F401
from . import scheduler
from madokabot.plugins.rss_subscription.commands.matchers import RSS_USAGE
from .config import DATA_PATH, RSSConfig
from .subscription import Rss
from .uploads.recovery import restore_upload_records

VERSION = "0.1.0"

__plugin_meta__ = PluginMetadata(
    name="订阅插件",
    description="Madoka机器人RSS订阅插件，主指令为RSS",
    usage=RSS_USAGE,
    type="application",
    homepage="https://github.com/Dyco/MadokaBot",
    config=RSSConfig,
    supported_adapters={"~onebot.v11"},
    extra={
        "author": "Dyco",
        "version": VERSION,
        "help_category": "拓展功能",
        "help_order": 40,
    },
)


def check_first_connect(_: LifecycleMetaEvent) -> bool:
    return True


start_metaevent = on_metaevent(rule=check_first_connect, temp=True)


@start_metaevent.handle()
async def start(bot: Bot) -> None:
    if not DATA_PATH.is_dir():
        DATA_PATH.mkdir(parents=True, exist_ok=True)

    rss_list = Rss.read_rss()
    # 上传恢复先于订阅初始化，单个源失败不能阻止恢复。
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
