"""注册 Steam 状态轮询任务。"""

from nonebot.log import logger
from nonebot_plugin_apscheduler import scheduler

from .config import config
from .monitor import broadcast_steam_info, update_steam_info


@scheduler.scheduled_job("interval", minutes=config.steam_request_interval / 60)
async def poll_steam_status():
    """按配置间隔刷新 Steam 状态并发送各群动态。"""
    try:
        snapshots = await update_steam_info()
        for group_id, (old_players, new_players, versions) in snapshots.items():
            await broadcast_steam_info(group_id, old_players, new_players, versions)
    except Exception as e:
        logger.error(f"Steam 自动播报任务执行失败: {e}")
