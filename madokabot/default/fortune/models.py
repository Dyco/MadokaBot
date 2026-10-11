"""每日运势与首次祈福奖励记录。"""

from datetime import date
from typing import Any

from sqlalchemy import Date, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from madokabot.core.db.base import data


class FortuneRecord(data.Model):
    """按用户与上海日期保存运势及已发奖励，跨会话共用首次祈福机会。"""

    __tablename__ = "madoka_daily_fortune_record"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    fortune_date: Mapped[date] = mapped_column(Date, primary_key=True)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    reward_points: Mapped[int] = mapped_column(Integer, nullable=False)
