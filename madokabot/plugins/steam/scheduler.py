"""注册 Steam 状态轮询任务。"""

from nonebot.log import logger
from nonebot_plugin_apscheduler import scheduler

from .config import config
from .monitor import broadcast_steam_info, update_steam_info
from .state import steam_groups, player_status


@scheduler.scheduled_job("interval", minutes=config.steam_request_interval / 60)
async def poll_steam_status():
    """按配置间隔刷新 Steam 状态并发送各群动态。"""
    try:
        old = await update_steam_info()
        for pid, old_players in old.items():
            new_players = player_status.get_players(steam_groups.get_steam_ids(pid))
            await broadcast_steam_info(pid, old_players, new_players)
    except Exception as e:
        logger.error(f"Steam 自动播报任务执行失败: {e}")
