"""每日次数与投胎结果的事务服务。"""

from zoneinfo import ZoneInfo

from nonebot_plugin_datastore import create_session
from sqlalchemy.exc import IntegrityError

from madokabot.core.db.base import shanghai_now
from .models import RebornRecord
from .simulation import simulate_rebirth


async def reborn_today(user_id: str) -> tuple[dict, bool]:
    """返回上海日期当天唯一结果；并发冲突时读取已提交结果，不重复消耗次数。"""
    today = shanghai_now().astimezone(ZoneInfo("Asia/Shanghai")).date()
    key = (user_id, today)
    async with create_session() as session:
        record = await session.get(RebornRecord, key)
        if record is not None:
            return dict(record.result), False

        result = simulate_rebirth()
        result["date"] = today.isoformat()
        session.add(RebornRecord(user_id=user_id, reborn_date=today, result=result))
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            record = await session.get(RebornRecord, key)
            if record is None:
                raise
            return dict(record.result), False
        return result, True
