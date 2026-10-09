"""共享用户表的历史结构兼容。"""

from sqlalchemy import DateTime, inspect
from nonebot_plugin_datastore.db import get_engine

from .models import UserStats


async def migrate_user_schema() -> None:
    """用户表结构补齐方法。"""
    engine = get_engine()
    async with engine.begin() as conn:
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

        if "display_name" not in columns:
            await conn.exec_driver_sql(
                f"ALTER TABLE {UserStats.__tablename__} "
                "ADD COLUMN display_name VARCHAR(10) NOT NULL DEFAULT ''"
            )

        if "sign_template" not in columns:
            await conn.exec_driver_sql(
                f"ALTER TABLE {UserStats.__tablename__} "
                "ADD COLUMN sign_template VARCHAR NOT NULL DEFAULT 'daily_sign_01.html'"
            )

        # 旧账号需补齐非空注册时间。
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
