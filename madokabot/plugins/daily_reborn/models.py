"""每日投胎的持久化记录。"""

from datetime import date
from typing import Any

from sqlalchemy import Date, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from madokabot.core.db.base import data


class RebornRecord(data.Model):
    """通过用户与日期联合主键保证跨群、重启及并发请求每天只有一次结果。"""

    __tablename__ = "madoka_daily_reborn_record"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    reborn_date: Mapped[date] = mapped_column(Date, primary_key=True)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ChinaRebornRecord(data.Model):
    """中国投胎的每日记录，与世界投胎分别计次并保留各自结果。"""

    __tablename__ = "madoka_daily_reborn_china_record"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    reborn_date: Mapped[date] = mapped_column(Date, primary_key=True)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class RebornProgress(data.Model):
    """按用户与模式保存累计次数及最近十次结果，不覆盖已有每日记录表。"""

    __tablename__ = "madoka_daily_reborn_progress"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    mode: Mapped[str] = mapped_column(String, primary_key=True)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    history: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
