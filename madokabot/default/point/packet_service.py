"""积分红包的扣款、领取与退款。"""

from datetime import datetime, timedelta, timezone
from secrets import randbelow
from uuid import uuid4

from nonebot_plugin_datastore import create_session
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from madokabot.core.user.models import UserStats

from .models import RedPacket, RedPacketClaim


def utc_now() -> datetime:
    """红包时间读取方法。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def create_red_packet(
    sender_id: str, bot_id: str, group_id: str, points: int, count: int,
) -> str:
    """红包创建方法。"""
    if count <= 0 or points < count:
        raise ValueError("积分和人数必须是正整数，且总积分不能少于人数")
    if points > 2**63 - 1:
        raise ValueError("红包积分数值过大")
    packet_id = uuid4().hex
    async with create_session() as session:
        deduction = await session.execute(
            update(UserStats)
            .where(UserStats.user_id == sender_id, UserStats.points >= points)
            .values(points=UserStats.points - points)
        )
        if deduction.rowcount != 1:
            await session.rollback()
            balance = await session.scalar(
                select(UserStats.points).where(UserStats.user_id == sender_id)
            )
            if balance is None:
                raise ValueError("请先发送“注册”完成用户注册")
            raise ValueError(f"积分不足，红包需要{points}积分，你当前持有{balance}积分")
        session.add(RedPacket(
            id=packet_id, bot_id=bot_id, group_id=group_id, sender_id=sender_id,
            total_points=points, remaining_points=points, remaining_count=count,
            state="pending", expires_at=utc_now() + timedelta(hours=1),
        ))
        await session.commit()
    return packet_id


async def activate_red_packet(packet_id: str, message_id: int) -> datetime:
    """红包消息关联方法。"""
    async with create_session() as session:
        expires_at = await session.scalar(
            update(RedPacket)
            .where(RedPacket.id == packet_id, RedPacket.state == "pending")
            .values(message_id=message_id, state="active", expires_at=utc_now() + timedelta(hours=1))
            .returning(RedPacket.expires_at)
        )
        if expires_at is None:
            raise RuntimeError("红包已关闭")
        await session.commit()
        return expires_at


def _reply_conditions(bot_id: str, group_id: str, message_id: int) -> tuple:
    """红包消息筛选方法。"""
    return (
        RedPacket.bot_id == bot_id,
        RedPacket.group_id == group_id,
        RedPacket.message_id == message_id,
        RedPacket.state == "active",
        RedPacket.expires_at > utc_now(),
    )


async def is_active_red_packet(bot_id: str, group_id: str, message_id: int) -> bool:
    """有效红包查询方法。"""
    async with create_session() as session:
        return await session.scalar(
            select(RedPacket.id).where(*_reply_conditions(bot_id, group_id, message_id))
        ) is not None


async def claim_red_packet(
    bot_id: str, group_id: str, message_id: int, uid: str,
) -> tuple[int, bool] | None:
    """红包领取方法。"""
    async with create_session() as session:
        # 更新红包行取得锁，领取和退款共用该行以避免并发重复结算。
        packet = await session.scalar(
            update(RedPacket)
            .where(*_reply_conditions(bot_id, group_id, message_id))
            .values(remaining_points=RedPacket.remaining_points)
            .returning(RedPacket)
        )
        if packet is None or packet.expires_at <= utc_now():
            return None
        if await session.get(RedPacketClaim, (packet.id, uid)) is not None:
            return None
        if packet.remaining_count == 1:
            points = packet.remaining_points
        else:
            maximum = min(
                packet.remaining_points - packet.remaining_count + 1,
                2 * packet.remaining_points // packet.remaining_count,
            )
            points = randbelow(maximum) + 1
        credit = await session.execute(
            update(UserStats).where(UserStats.user_id == uid)
            .values(points=UserStats.points + points)
        )
        if credit.rowcount != 1:
            await session.rollback()
            return None
        session.add(RedPacketClaim(
            packet_id=packet.id, user_id=uid, points=points, claimed_at=utc_now(),
        ))
        packet.remaining_points -= points
        packet.remaining_count -= 1
        finished = packet.remaining_count == 0
        if finished:
            packet.state = "finished"
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return None
        return points, finished


async def refund_red_packet(packet_id: str, *, expired_only: bool = True) -> bool:
    """红包退款方法。"""
    conditions = [RedPacket.id == packet_id, RedPacket.state.in_(("pending", "active"))]
    if expired_only:
        conditions.append(RedPacket.expires_at <= utc_now())
    async with create_session() as session:
        packet = await session.scalar(
            update(RedPacket).where(*conditions)
            .values(state="refunded").returning(RedPacket)
        )
        if packet is None:
            return False
        credit = await session.execute(
            update(UserStats).where(UserStats.user_id == packet.sender_id)
            .values(points=UserStats.points + packet.remaining_points)
        )
        if credit.rowcount != 1:
            raise LookupError("红包发送者账号不存在，保留退款记录等待重试")
        packet.remaining_points = 0
        packet.remaining_count = 0
        await session.commit()
        return True


async def get_open_red_packets() -> list[tuple[str, datetime]]:
    """未结束红包查询方法。"""
    async with create_session() as session:
        result = await session.execute(
            select(RedPacket.id, RedPacket.expires_at)
            .where(RedPacket.state.in_(("pending", "active")))
        )
        return list(result.tuples().all())
