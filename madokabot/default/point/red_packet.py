"""积分红包命令、领取监听与到期调度。"""

from datetime import datetime, timezone

from nonebot import get_bot, logger, on_message
from nonebot.adapters.onebot.v11 import (
    Bot, GroupMessageEvent, MessageEvent, MessageSegment,
)
from nonebot_plugin_alconna import Match
from nonebot_plugin_apscheduler import scheduler
from nonebot_plugin_datastore import create_session
from nonebot_plugin_datastore.db import post_db_init

from madokabot.core.config import command_start
from madokabot.core.messaging.pagination import extract_message_id
from madokabot.core.messaging.response import respond
from madokabot.core.user.models import UserStats
from madokabot.default.account.service import register_user

from .matchers import point_cmd
from .packet_service import (
    MAX_RED_PACKET_COUNT,
    activate_red_packet,
    claim_red_packet,
    create_red_packet,
    get_open_red_packets,
    get_red_packet_summary,
    is_active_red_packet,
    refund_red_packet,
    utc_now,
)


async def send_red_packet_summary(packet_id: str) -> None:
    """红包汇总发送方法。"""
    try:
        summary = await get_red_packet_summary(packet_id)
        if summary is None:
            return
        bot_id, group_id, message_id, text = summary
        await get_bot(bot_id).send_group_msg(
            group_id=int(group_id),
            message=MessageSegment.reply(message_id) + MessageSegment.text(text),
        )
    except Exception:
        logger.exception(f"红包领取汇总发送失败：{packet_id}")


async def refund_expired_red_packet(packet_id: str) -> None:
    """到期红包退款方法。"""
    try:
        refunded = await refund_red_packet(packet_id)
    except Exception:
        logger.exception(f"红包退款失败，等待重试：{packet_id}")
        return
    if refunded:
        await send_red_packet_summary(packet_id)


def schedule_red_packet_refund(packet_id: str, expires_at: datetime) -> None:
    """红包退款调度方法。"""
    scheduler.add_job(
        refund_expired_red_packet,
        "date",
        run_date=expires_at.replace(tzinfo=timezone.utc),
        args=[packet_id],
        id=f"madokabot_point_packet_{packet_id}",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=None,
    )


@scheduler.scheduled_job(
    "interval", minutes=1, id="madokabot_point_packet_recovery",
    max_instances=1, coalesce=True,
)
async def recover_red_packets() -> None:
    """红包恢复方法。"""
    try:
        packets = await get_open_red_packets()
    except Exception:
        logger.exception("读取待恢复红包失败")
        return
    for packet_id, expires_at in packets:
        try:
            if expires_at <= utc_now():
                await refund_expired_red_packet(packet_id)
            elif scheduler.get_job(f"madokabot_point_packet_{packet_id}") is None:
                schedule_red_packet_refund(packet_id, expires_at)
        except Exception:
            logger.exception(f"红包调度恢复失败：{packet_id}")


@post_db_init
async def schedule_red_packet_recovery() -> None:
    """启动红包恢复调度方法。"""
    scheduler.add_job(
        recover_red_packets,
        "date",
        run_date=datetime.now(timezone.utc),
        id="madokabot_point_packet_startup",
        replace_existing=True,
        misfire_grace_time=None,
    )


@point_cmd.assign("packet")
async def handle_red_packet(
    bot: Bot, event: MessageEvent, points: Match[str], count: Match[str],
) -> None:
    """红包发送命令处理方法。"""
    if not isinstance(event, GroupMessageEvent):
        await point_cmd.finish("请在群聊中发送积分红包", reply_message=True)
    if not points.available or not count.available:
        await point_cmd.finish(f"用法：{command_start}积分 红包 <总积分> <人数>", reply_message=True)
    raw_points, raw_count = points.result.strip(), count.result.strip()
    if not all(value.isascii() and value.isdecimal() for value in (raw_points, raw_count)):
        await point_cmd.finish("红包积分和人数必须是正整数", reply_message=True)
    try:
        total_points, people = int(raw_points), int(raw_count)
    except ValueError:
        await point_cmd.finish("红包数值过大", reply_message=True)
    people = min(people, MAX_RED_PACKET_COUNT)
    try:
        packet_id = await create_red_packet(
            event.get_user_id(), bot.self_id, str(event.group_id), total_points, people
        )
    except ValueError as exc:
        await point_cmd.finish(str(exc), reply_message=True)
    except Exception:
        logger.exception("积分红包创建失败")
        await point_cmd.finish("红包暂时无法发送，请稍后重试", reply_message=True)

    message_id = None
    name = event.sender.card or event.sender.nickname or f"QQ{event.user_id}"
    try:
        sent = await point_cmd.send(MessageSegment.text(
            f"{name}发了红包！\n{people}人可抢，总计{total_points}积分！\n回复此消息即可抢红包"
        ), reply_message=True)
        message_id = extract_message_id(sent)
        if message_id is None:
            raise RuntimeError("红包消息编号缺失")
        expires_at = await activate_red_packet(packet_id, message_id)
    except Exception:
        logger.exception("红包消息发送或关联失败")
        try:
            await refund_red_packet(packet_id, expired_only=False)
        except Exception:
            logger.exception("红包发送失败后退款异常，保留记录等待到期退款")
            await point_cmd.finish("红包发送失败，剩余积分将在到期后自动退回", reply_message=True)
        if message_id is not None:
            try:
                await bot.delete_msg(message_id=message_id)
            except Exception:
                logger.warning("未能撤回已关闭的红包消息")
        await point_cmd.finish("红包发送失败，剩余积分已退回", reply_message=True)
    try:
        schedule_red_packet_refund(packet_id, expires_at)
    except Exception:
        logger.exception("红包退款调度失败，等待定时恢复")
    await point_cmd.finish()


async def is_red_packet_reply(bot: Bot, event: MessageEvent) -> bool:
    """红包回复识别方法。"""
    if not isinstance(event, GroupMessageEvent) or event.reply is None:
        return False
    try:
        return await is_active_red_packet(bot.self_id, str(event.group_id), event.reply.message_id)
    except Exception:
        logger.exception("红包回复识别失败")
        return False


red_packet_reply = on_message(rule=is_red_packet_reply, priority=8, block=False)


@red_packet_reply.handle()
async def handle_red_packet_reply(bot: Bot, event: GroupMessageEvent) -> None:
    """处理红包领取回复，播报本次积分与红包剩余数量、积分。"""
    if event.reply is None:
        return
    try:
        async with create_session() as session:
            if await session.get(UserStats, event.get_user_id()) is None:
                await register_user(session, event.get_user_id(), event.sender.nickname or "")
        claimed = await claim_red_packet(
            bot.self_id, str(event.group_id), event.reply.message_id, event.get_user_id()
        )
    except Exception:
        logger.exception("积分红包领取失败")
        return
    if claimed is None:
        return
    await respond(bot, event, emoji_id=478)
    points, remaining_count, remaining_points, packet_id = claimed
    name = event.sender.card or event.sender.nickname or f"QQ{event.user_id}"
    try:
        await bot.send_group_msg(
            group_id=event.group_id,
            message=MessageSegment.reply(event.message_id)
            + MessageSegment.text(
                f"{name}抢到{points}积分，还剩{remaining_count}个红包，{remaining_points}积分！"
            ),
        )
    except Exception:
        logger.exception("红包领取积分播报失败")
    if remaining_count == 0:
        await send_red_packet_summary(packet_id)
