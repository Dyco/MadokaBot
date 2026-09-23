"""CS 赛事轮询与超时竞猜退款定时任务。"""

from __future__ import annotations

from datetime import datetime, timezone

from nonebot import logger
from nonebot_plugin_apscheduler import scheduler

from .config import config
from .prediction import refund_expired_predictions
from .subscriptions.polling import poll_subscriptions


@scheduler.scheduled_job(
    "interval",
    seconds=config.hltv_poll_interval,
    id="madokabot_cs_match_subscribe_poll",
    max_instances=1,
    coalesce=True,
    # 机器人重启后立即检查持久化状态，避免错过赛事开始后的第一次轮询。
    next_run_time=datetime.now(timezone.utc),
)
async def poll_cs_match_subscriptions() -> None:
    """按配置间隔执行赛事订阅轮询。"""
    await poll_subscriptions()


@scheduler.scheduled_job(
    "interval",
    minutes=5,
    id="madokabot_cs_prediction_refund_expired",
    max_instances=1,
    coalesce=True,
    next_run_time=datetime.now(timezone.utc),
)
async def refund_expired_cs_predictions() -> None:
    """独立于网络抓取和订阅列表的竞猜退款兜底，只记录日志。"""
    try:
        await refund_expired_predictions()
    except Exception:
        logger.exception("CS 超时竞猜退款失败，将在下一轮重试")
