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
    qq_nickname: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    register_time: Mapped[datetime] = mapped_column(
        DateTime,
        default=_shanghai_now,
        nullable=False,
    )
    points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    favorability: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skin_asset: Mapped[str] = mapped_column(String, default="", nullable=False)


class CsPrediction(data.Model):
    """CS 赛事竞猜记录。"""

    __tablename__ = "cs_prediction_record"

    event_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    match_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    group_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    team_name: Mapped[str] = mapped_column(String(128), nullable=False)
    points: Mapped[int] = mapped_column(Integer, nullable=False)
    payout: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    net_points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    result: Mapped[str] = mapped_column(String(16), default="open", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=_shanghai_now,
        nullable=False,
    )
    settled_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        default=None,
        nullable=True,
    )


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

        if "qq_nickname" not in columns:
            await conn.exec_driver_sql(
                f"ALTER TABLE {UserStats.__tablename__} "
                "ADD COLUMN qq_nickname VARCHAR(64) DEFAULT ''"
            )

        # 旧数据库没有注册时间，补值后才能满足模型的非空约束。
        await conn.exec_driver_sql(
            f"UPDATE {UserStats.__tablename__} "
            "SET register_time = CURRENT_TIMESTAMP "
            "WHERE register_time IS NULL"
        )
        await conn.exec_driver_sql(
            f"UPDATE {UserStats.__tablename__} "
            "SET qq_nickname = '' "
            "WHERE qq_nickname IS NULL"
        )
