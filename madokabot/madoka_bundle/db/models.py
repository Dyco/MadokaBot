from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from nonebot_plugin_datastore import get_plugin_data
from nonebot_plugin_datastore.db import get_engine

data = get_plugin_data("madoka_bundle")


class UserStats(data.Model):
    __tablename__ = "madoka_user_stats"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    points: Mapped[int] = mapped_column(Integer, default=0)
    favorability: Mapped[int] = mapped_column(Integer, default=0)
    skin_key: Mapped[str] = mapped_column(String(32), default="skin08")


class SignRecord(data.Model):
    __tablename__ = "madoka_sign_record"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    last_sign_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    continuous_days: Mapped[int] = mapped_column(Integer, default=0)
    total_count: Mapped[int] = mapped_column(Integer, default=0)


class ShopItem(data.Model):
    __tablename__ = "madoka_shop_item"

    item_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    item_type: Mapped[str] = mapped_column(String(32), default="skin")
    asset_name: Mapped[str] = mapped_column(String, default="")
    price: Mapped[int] = mapped_column(Integer)
    stock: Mapped[int] = mapped_column(Integer, default=-1)
    description: Mapped[str] = mapped_column(String, default="")
    is_active: Mapped[int] = mapped_column(Integer, default=1)


class UserInventory(data.Model):
    __tablename__ = "madoka_user_inventory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String)
    item_id: Mapped[int] = mapped_column(Integer)
    count: Mapped[int] = mapped_column(Integer, default=1)


class UserSkin(data.Model):
    __tablename__ = "madoka_user_skins"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    skin_key: Mapped[str] = mapped_column(String(32), index=True)


async def _ensure_shop_item_columns() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        result = await conn.exec_driver_sql("PRAGMA table_info(madoka_shop_item)")
        columns = {row[1] for row in result.fetchall()}

        if not columns:
            return

        if "item_key" not in columns:
            await conn.exec_driver_sql(
                "ALTER TABLE madoka_shop_item ADD COLUMN item_key VARCHAR(64)"
            )
        if "item_type" not in columns:
            await conn.exec_driver_sql(
                "ALTER TABLE madoka_shop_item ADD COLUMN item_type VARCHAR(32) DEFAULT 'skin'"
            )
        if "asset_name" not in columns:
            await conn.exec_driver_sql(
                "ALTER TABLE madoka_shop_item ADD COLUMN asset_name VARCHAR DEFAULT ''"
            )
        if "is_active" not in columns:
            await conn.exec_driver_sql(
                "ALTER TABLE madoka_shop_item ADD COLUMN is_active INTEGER DEFAULT 1"
            )

        await conn.exec_driver_sql(
            "UPDATE madoka_shop_item "
            "SET item_key = COALESCE(NULLIF(item_key, ''), name), "
            "item_type = COALESCE(NULLIF(item_type, ''), 'skin'), "
            "asset_name = COALESCE(NULLIF(asset_name, ''), name), "
            "is_active = COALESCE(is_active, 1)"
        )


async def init_madoka_db():
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(data.Model.metadata.create_all)
    await _ensure_shop_item_columns()
