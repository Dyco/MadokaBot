"""赛事与竞猜通知的合并转发和多目标发送。"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable

from nonebot import get_bots, logger
from nonebot.adapters.onebot.v11 import Bot, Message, MessageSegment

from ..prediction import mark_prediction_notification_sent, prediction_notification_was_sent
from ..subscriptions.notifications import MatchNotification

_DELIVERY_LOCK = asyncio.Lock()


async def send_forward_to_target(
    bot: Bot,
    target: dict[str, str],
    messages: list[Message],
) -> bool:
    """合并消息发送方法。"""
    kind = target.get("kind")
    target_id = target.get("id")
    if not target_id or not messages:
        return False

    sender_id = int(str(bot.self_id)) if str(bot.self_id).isdigit() else 0
    nodes = [
        MessageSegment.node_custom(sender_id, "HLTV赛事订阅", content)
        for content in messages
    ]
    if kind == "group":
        await bot.send_group_forward_msg(
            group_id=int(target_id),
            messages=nodes,
        )
        return True
    if kind == "private":
        await bot.send_private_forward_msg(
            user_id=int(target_id),
            messages=nodes,
        )
        return True
    return False


async def send_rating_forward(
    bot: Bot,
    target: dict[str, str],
    messages: list[Message],
) -> bool:
    """发送比赛 Rating 图片合并转发。"""
    return await send_forward_to_target(bot, target, messages)


def available_bots() -> Iterable[Bot]:
    """可用机器人连接查询方法。"""
    return [bot for bot in get_bots().values() if isinstance(bot, Bot)]


async def send_event_notifications_to_target(
    bot: Bot,
    target: dict[str, str],
    notifications: list[MatchNotification],
) -> bool:
    """将同轮赛事与竞猜通知按原顺序合并发送给目标。"""
    return await send_forward_to_target(
        bot,
        target,
        [notification.message for notification in notifications],
    )


async def _broadcast_target_notifications(
    target_notifications: list[tuple[dict[str, str], list[MatchNotification]]],
) -> bool:
    """群通知广播方法。"""
    valid_target_notifications = [
        (target, notifications)
        for target, notifications in target_notifications
        if notifications
    ]
    bots = list(available_bots())
    if not bots:
        logger.warning("没有可用 OneBot 连接，暂不推送 HLTV 赛事更新。")
        return False
    if not valid_target_notifications:
        logger.warning("HLTV 赛事订阅没有有效推送目标，暂不更新订阅状态。")
        return False

    delivered_any = False
    failed_targets: list[dict[str, str]] = []
    for target, notifications in valid_target_notifications:
        receipts = [item for item in notifications if item.kind == "prediction_settlement"]
        suppressed = set()
        for item in receipts:
            if await prediction_notification_was_sent(item.event_id, item.match_id, target["id"]):
                suppressed.add(item.match_id)
        notifications = [item for item in notifications if item.match_id not in suppressed]
        if not notifications:
            delivered_any = True
            continue
        delivered = False
        for bot in bots:
            try:
                if await send_event_notifications_to_target(
                    bot,
                    target,
                    notifications,
                ):
                    delivered = True
                    break
            except Exception:
                logger.exception("推送 HLTV 赛事通知失败：%s", target)
        if delivered:
            delivered_any = True
            for item in receipts:
                if item.match_id not in suppressed:
                    await mark_prediction_notification_sent(
                        item.event_id, item.match_id, target["id"],
                    )
        else:
            failed_targets.append(target)

    if delivered_any and failed_targets:
        logger.warning(
            "HLTV 赛事更新仅部分送达；已提交本轮状态以避免成功目标重复收取，"
            "失败目标：%s",
            failed_targets,
        )
    return delivered_any


async def broadcast_target_notifications(
    target_notifications: list[tuple[dict[str, str], list[MatchNotification]]],
) -> bool:
    """竞猜通知去重发送方法。"""
    async with _DELIVERY_LOCK:
        return await _broadcast_target_notifications(target_notifications)
