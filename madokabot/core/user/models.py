"""共享用户领域的数据模型。"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from madokabot.core.db.base import data, shanghai_now


class UserStats(data.Model):
    """跨功能共享的账号资料、积分与当前立绘。"""

    __tablename__ = "madoka_user_stats"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    qq_nickname: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    display_name: Mapped[str] = mapped_column(String(10), default="", nullable=False)
    # 付费设置的账号显示名，留空时沿用 QQ 昵称或群名片。
    register_time: Mapped[datetime] = mapped_column(
        DateTime,
        default=shanghai_now,
        nullable=False,
    )
    points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    favorability: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skin_asset: Mapped[str] = mapped_column(String, default="", nullable=False)


class SignRecord(data.Model):
    """注册、签到、资料卡和排行榜共同使用的签到统计。"""

    __tablename__ = "madoka_sign_record"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    last_sign_date: Mapped[datetime | None] = mapped_column(
        DateTime,
        default=None,
        nullable=True,
    )
    continuous_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
