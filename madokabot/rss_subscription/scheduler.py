import asyncio
import re

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from async_timeout import timeout
from nonebot.log import logger
from nonebot_plugin_apscheduler import scheduler

from . import feed
from .subscription import Rss


async def check_update(rss: Rss) -> None:
    logger.info(f"{rss.name} 检查更新")
    try:
        wait_for = (
            5 * 60
            if re.search(r"[_*/,-]", rss.time)
            else int(rss.time) * 60
        )
        async with timeout(wait_for):
            await feed.start(rss)
    except asyncio.CancelledError:
        raise
    except asyncio.TimeoutError:
        logger.error(f"{rss.name} 检查更新超时，结束此次任务!")
    except Exception:
        logger.exception(f"{rss.name} 检查更新失败，结束此次任务!")


def delete_job(rss: Rss) -> None:
    if scheduler.get_job(rss.name):
        scheduler.remove_job(rss.name)


async def add_job(rss: Rss) -> None:
    delete_job(rss)
    if any([rss.user_id, rss.group_id, rss.guild_channel_id]):
        schedule_job(rss)
        await check_update(rss)


def schedule_job(rss: Rss) -> None:
    if re.search(r"[_*/,-]", rss.time):
        schedule_cron_job(rss)
        return
    trigger = IntervalTrigger(minutes=int(rss.time), jitter=10)
    scheduler.add_job(
        func=check_update,
        trigger=trigger,
        args=(rss,),
        id=rss.name,
        misfire_grace_time=30,
        max_instances=1,
        executor="default",
        coalesce=True,
    )
    logger.info(f"定时任务 {rss.name} 添加成功")


def schedule_cron_job(rss: Rss) -> None:
    tmp_list = rss.time.split("_")
    times_list = ["*/5", "*", "*", "*", "*"]
    for index, value in enumerate(tmp_list):
        if value:
            times_list[index] = value
    try:
        trigger = CronTrigger(
            minute=times_list[0],
            hour=times_list[1],
            day=times_list[2],
            month=times_list[3],
            day_of_week=times_list[4],
        )
    except Exception:
        logger.exception(f"创建定时器错误！cron:{times_list}")
        return

    scheduler.add_job(
        func=check_update,
        trigger=trigger,
        args=(rss,),
        id=rss.name,
        misfire_grace_time=30,
        max_instances=1,
        executor="default",
        coalesce=True,
    )
    logger.info(f"定时任务 {rss.name} 添加成功")
