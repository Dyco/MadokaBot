"""共享用户领域的数据模型。"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from madokabot.core.db.base import data, shanghai_now


class UserStats(data.Model):
    """积分账号资料。"""

    __tablename__ = "madoka_user_stats"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    qq_nickname: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    display_name: Mapped[str] = mapped_column(String(10), default="", nullable=False)
    register_time: Mapped[datetime] = mapped_column(
        DateTime,
        default=shanghai_now,
        nullable=False,
    )
    points: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    favorability: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skin_asset: Mapped[str] = mapped_column(String, default="", nullable=False)
    sign_template: Mapped[str] = mapped_column(
        String, default="daily_sign_01.html", nullable=False
    )


class UserProfile(data.Model):
    """未注册也可保存的基础用户资料。"""

    __tablename__ = "madoka_user_profile"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    qq_nickname: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=shanghai_now, nullable=False
    )


class SignRecord(data.Model):
    """用户签到统计。"""

    __tablename__ = "madoka_sign_record"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    last_sign_date: Mapped[datetime | None] = mapped_column(
        DateTime,
        default=None,
        nullable=True,
    )
    continuous_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
