"""全局许愿池与每日参与记录。"""

from datetime import date

from sqlalchemy import Date, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from madokabot.core.db.base import data


class WishPool(data.Model):
    """使用固定编号保存全局共享奖池。"""

    __tablename__ = "madoka_wish_pool"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class WishRecord(data.Model):
    """按用户与上海日期唯一记录参与次数，跨会话共用每日机会。"""

    __tablename__ = "madoka_wish_record"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    wish_date: Mapped[date] = mapped_column(Date, primary_key=True)
