from datetime import datetime
from typing import Optional
from sqlalchemy import String, Integer, DateTime, select
from sqlalchemy.orm import Mapped, mapped_column

from nonebot_plugin_datastore import get_plugin_data, create_session
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
    name: Mapped[str] = mapped_column(String, unique=True)
    price: Mapped[int] = mapped_column(Integer)
    stock: Mapped[int] = mapped_column(Integer, default=-1)
    description: Mapped[str] = mapped_column(String, default="")

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


#初始化
async def init_madoka_db():
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(data.Model.metadata.create_all)