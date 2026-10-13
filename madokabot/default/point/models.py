"""积分红包数据模型。"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from madokabot.core.db.base import data


class RedPacket(data.Model):
    """红包记录。"""

    __tablename__ = "madoka_point_red_packet"
    __table_args__ = (
        UniqueConstraint("bot_id", "group_id", "message_id"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    bot_id: Mapped[str] = mapped_column(String, nullable=False)
    group_id: Mapped[str] = mapped_column(String, nullable=False)
    message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sender_id: Mapped[str] = mapped_column(String, nullable=False)
    total_points: Mapped[int] = mapped_column(Integer, nullable=False)
    remaining_points: Mapped[int] = mapped_column(Integer, nullable=False)
    remaining_count: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), default="pending", nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)


class RedPacketClaim(data.Model):
    """红包领取记录。"""

    __tablename__ = "madoka_point_red_packet_claim"

    packet_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    points: Mapped[int] = mapped_column(Integer, nullable=False)
    claimed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
