"""每日投胎的持久化记录。"""

from datetime import date
from typing import Any

from sqlalchemy import Date, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from madokabot.core.db.base import data


class RebornRecord(data.Model):
    """通过用户与日期联合主键保证跨群、重启及并发请求每天只有一次结果。"""

    __tablename__ = "madoka_daily_reborn_record"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    reborn_date: Mapped[date] = mapped_column(Date, primary_key=True)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
