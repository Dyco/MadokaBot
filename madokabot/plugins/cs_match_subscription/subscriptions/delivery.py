"""赛事普通消息、合并转发与多目标发送。"""

from __future__ import annotations

from collections.abc import Iterable

from nonebot import get_bots, logger
from nonebot.adapters.onebot.v11 import Bot, Message, MessageSegment

from ..subscriptions.notifications import MatchNotification


async def send_forward_to_target(
    bot: Bot,
    target: dict[str, str],
    messages: list[Message],
) -> bool:
    """通过 OneBot 的 forward API 发送自定义节点。"""
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


async def send_message_to_target(
    bot: Bot,
    target: dict[str, str],
    message: Message,
) -> bool:
    """向赛事订阅目标发送一条普通消息。"""
    kind = target.get("kind")
    target_id = target.get("id")
    if not target_id or not message:
        return False
    if kind == "group":
        await bot.send_group_msg(
            group_id=int(target_id),
            message=message,
        )
        return True
    if kind == "private":
        await bot.send_private_msg(
            user_id=int(target_id),
            message=message,
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
    """获取当前可用于推送的 OneBot V11 连接。"""
    return [bot for bot in get_bots().values() if isinstance(bot, Bot)]


async def broadcast_forward(
    targets: list[dict[str, str]],
    messages: list[Message],
) -> bool:
    """将同一赛事更新批次作为合并转发广播。"""
    return await broadcast_target_forwards([(target, messages) for target in targets])


async def broadcast_target_forwards(
    target_messages: list[tuple[dict[str, str], list[Message]]],
) -> bool:
    """按目标分别发送赛事更新批次。

    返回值表示本批次是否至少送达一个目标。赛事状态是所有订阅目标共享的；
    如果部分目标已经成功、部分目标失败，仍必须提交状态，否则成功目标会在
    下一轮再次收到完全相同的比赛状态。
    """
    target_messages = [
        (target, messages) for target, messages in target_messages if messages
    ]
    bots = list(available_bots())
    if not bots:
        logger.warning("没有可用 OneBot 连接，暂不推送 HLTV 赛事更新。")
        return False
    if not target_messages:
        logger.warning("HLTV 赛事订阅没有有效推送目标，暂不更新订阅状态。")
        return False

    delivered_any = False
    failed_targets: list[dict[str, str]] = []
    for target, messages in target_messages:
        delivered = False
        for bot in bots:
            try:
                if await send_forward_to_target(bot, target, messages):
                    delivered = True
                    break
            except Exception:
                logger.exception("推送 HLTV 合并转发失败：%s", target)
        if delivered:
            delivered_any = True
        else:
            failed_targets.append(target)

    if delivered_any and failed_targets:
        logger.warning(
            "HLTV 赛事更新仅部分送达；已提交本轮状态以避免成功目标重复收取，"
            "失败目标：%s",
            failed_targets,
        )
    return delivered_any


async def send_event_notifications_to_target(
    bot: Bot,
    target: dict[str, str],
    notifications: list[MatchNotification],
) -> bool:
    """按通知类型发送赛事更新，竞猜通知使用普通消息。"""
    prediction_kinds = {"prediction_open", "prediction_close"}
    forward_messages = [
        notification.message
        for notification in notifications
        if notification.kind not in prediction_kinds
    ]
    prediction_messages = [
        notification.message
        for notification in notifications
        if notification.kind in prediction_kinds
    ]
    if forward_messages and not await send_forward_to_target(
        bot,
        target,
        forward_messages,
    ):
        return False
    for message in prediction_messages:
        if not await send_message_to_target(bot, target, message):
            return False
    return bool(forward_messages or prediction_messages)


async def broadcast_target_notifications(
    target_notifications: list[tuple[dict[str, str], list[MatchNotification]]],
) -> bool:
    """按目标发送赛事通知，竞猜节点不包装为合并消息。"""
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
        else:
            failed_targets.append(target)

    if delivered_any and failed_targets:
        logger.warning(
            "HLTV 赛事更新仅部分送达；已提交本轮状态以避免成功目标重复收取，"
            "失败目标：%s",
            failed_targets,
        )
    return delivered_any
