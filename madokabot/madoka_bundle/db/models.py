from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import DateTime, Integer, String, inspect
from sqlalchemy.orm import Mapped, mapped_column

from nonebot_plugin_datastore import get_plugin_data
from nonebot_plugin_datastore.db import get_engine

data = get_plugin_data("madoka_bundle")

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def _shanghai_now() -> datetime:
    return datetime.now(_SHANGHAI_TZ)


class UserStats(data.Model):
    __tablename__ = "madoka_user_stats"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    register_time: Mapped[datetime] = mapped_column(
        DateTime,
        default=_shanghai_now,
        nullable=False,
    )
    points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    favorability: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skin_asset: Mapped[str] = mapped_column(String, default="", nullable=False)


class SignRecord(data.Model):
    __tablename__ = "madoka_sign_record"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    last_sign_date: Mapped[datetime | None] = mapped_column(
        DateTime,
        default=None,
        nullable=True,
    )
    continuous_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class UserInventory(data.Model):
    __tablename__ = "madoka_user_inventory"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    resource_type: Mapped[str] = mapped_column("type", String(32), primary_key=True)
    content: Mapped[str] = mapped_column(String(32), primary_key=True)
    file_name: Mapped[str] = mapped_column(String, primary_key=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)


async def init_madoka_db() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(data.Model.metadata.create_all)
        columns = await conn.run_sync(
            lambda sync_conn: {
                column["name"]
                for column in inspect(sync_conn).get_columns(UserStats.__tablename__)
            }
        )
        if "register_time" not in columns:
            column_type = DateTime().compile(dialect=conn.dialect)
            await conn.exec_driver_sql(
                f"ALTER TABLE {UserStats.__tablename__} "
                f"ADD COLUMN register_time {column_type}"
            )

        # 旧数据库没有注册时间，补值后才能满足模型的非空约束。
        await conn.exec_driver_sql(
            f"UPDATE {UserStats.__tablename__} "
            "SET register_time = CURRENT_TIMESTAMP "
            "WHERE register_time IS NULL"
        )
