"""CS 赛事轮询与未结算竞猜恢复定时任务。"""

from __future__ import annotations

from datetime import datetime, timezone

from nonebot import get_driver, logger
from nonebot_plugin_apscheduler import scheduler
from nonebot_plugin_datastore.db import post_db_init

from .config import config
from .subscriptions.polling import poll_subscriptions
from .subscriptions.settlement import (
    reconcile_unsettled_predictions,
    send_pending_prediction_notifications,
)


@scheduler.scheduled_job(
    "interval",
    seconds=config.hltv_poll_interval,
    id="madokabot_cs_match_subscribe_poll",
    max_instances=1,
    coalesce=True,
    next_run_time=datetime.now(timezone.utc),
)
async def poll_cs_match_subscriptions() -> None:
    """按配置间隔执行赛事订阅轮询。"""
    await poll_subscriptions()


async def reconcile_cs_predictions() -> None:
    """启动竞猜补结算方法。"""
    try:
        await reconcile_unsettled_predictions()
    except Exception:
        logger.exception("CS 启动补结算失败，保留下注等待比赛结束或下次启动")


@post_db_init
async def schedule_prediction_recovery() -> None:
    """竞猜恢复任务调度方法。"""
    scheduler.add_job(
        reconcile_cs_predictions,
        "date",
        run_date=datetime.now(timezone.utc),
        id="madokabot_cs_prediction_refund_expired",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=None,
    )


@get_driver().on_bot_connect
async def send_prediction_notifications_on_connect() -> None:
    """连接就绪通知补发方法。"""
    try:
        await send_pending_prediction_notifications(ready_only=True)
    except Exception:
        logger.exception("CS 连接恢复后发送结算通知失败，保留凭据等待重试")
