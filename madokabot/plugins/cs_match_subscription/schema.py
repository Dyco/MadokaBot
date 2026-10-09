"""竞猜记录对阵快照字段的结构补齐。"""

from nonebot_plugin_datastore import create_session
from nonebot_plugin_datastore.db import get_engine, post_db_init
from sqlalchemy import inspect, or_, select, update

from .prediction_models import CsPrediction
from .storage import get_prediction_match_states


@post_db_init
async def migrate_prediction_schema() -> None:
    """补齐双方队名字段，并利用已有比赛快照填充历史记录。"""
    async with get_engine().begin() as connection:
        columns = await connection.run_sync(
            lambda sync_connection: {
                column["name"]
                for column in inspect(sync_connection).get_columns(CsPrediction.__tablename__)
            }
        )
        if "team1_name" not in columns:
            await connection.exec_driver_sql(
                "ALTER TABLE cs_prediction_record "
                "ADD COLUMN team1_name VARCHAR(128) NOT NULL DEFAULT ''"
            )
        if "team2_name" not in columns:
            await connection.exec_driver_sql(
                "ALTER TABLE cs_prediction_record "
                "ADD COLUMN team2_name VARCHAR(128) NOT NULL DEFAULT ''"
            )

    missing_teams = or_(CsPrediction.team1_name == "", CsPrediction.team2_name == "")
    async with create_session() as session:
        match_keys = (await session.execute(
            select(CsPrediction.event_id, CsPrediction.match_id)
            .where(missing_teams).distinct()
        )).all()
        states = await get_prediction_match_states(match_keys)
        for (event_id, match_id), state in states.items():
            teams = state.get("team_names") or []
            if len(teams) < 2:
                continue
            await session.execute(
                update(CsPrediction).where(
                    CsPrediction.event_id == event_id,
                    CsPrediction.match_id == match_id,
                    missing_teams,
                ).values(team1_name=teams[0], team2_name=teams[1])
            )
        await session.commit()
