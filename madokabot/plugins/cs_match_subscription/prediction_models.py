"""CS 竞猜的持久化模型。"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from madokabot.core.db.base import data, shanghai_now


class CsPrediction(data.Model):
    """CS 赛事竞猜记录。"""

    __tablename__ = "cs_prediction_record"

    event_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    match_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    group_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    team_name: Mapped[str] = mapped_column(String(128), nullable=False)
    # 保存下注时的完整对阵，避免历史页面依赖仍在订阅的比赛快照。
    team1_name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    team2_name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    points: Mapped[int] = mapped_column(Integer, nullable=False)
    payout: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    net_points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    result: Mapped[str] = mapped_column(String(16), default="open", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=shanghai_now,
        nullable=False,
    )
    settled_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        default=None,
        nullable=True,
    )


class CsPredictionNotification(data.Model):
    """竞猜群通知凭据。"""

    __tablename__ = "cs_prediction_notification"

    event_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    match_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    group_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    winner_name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    # 保留已有数据库字段，赔率结算不再使用公池。
    public_pool: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    final_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
