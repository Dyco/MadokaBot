"""机器人入群提示与群规模自动退群。"""

import asyncio

from nonebot import logger, on_notice
from nonebot.adapters.onebot.v11 import Bot, GroupIncreaseNoticeEvent

from .config import config
from madokabot.core.group.access import is_group_whitelisted


AUTO_LEAVE_DELAY_SECONDS = 3 * 60
_leave_tasks: dict[tuple[int, int], asyncio.Task[None]] = {}


def should_auto_leave_group(member_count: int) -> bool:
    """判断群人数是否命中自动退群条件。"""
    return (
        member_count < config.auto_leave_group_min_members
        or member_count > config.auto_leave_group_max_members
    )


async def _leave_group_after_delay(bot: Bot, group_id: int) -> None:
    """发送入群提示，延迟复核白名单和群人数后决定是否退出。"""
    await _notify_group_join(bot, group_id)
    await asyncio.sleep(AUTO_LEAVE_DELAY_SECONDS)

    if is_group_whitelisted(group_id):
        logger.info(f"群 {group_id} 已加入白名单，取消自动退群")
        return

    try:
        group_info = await bot.call_api(
            "get_group_info", group_id=group_id, no_cache=True
        )
        member_count = int(group_info["member_count"])
    except Exception:
        logger.exception(f"获取群 {group_id} 信息失败，取消自动退群")
        return

    if not should_auto_leave_group(member_count):
        logger.info(f"群 {group_id} 当前人数为 {member_count}，取消自动退群")
        return

    try:
        await bot.call_api(
            "set_group_leave",
            group_id=group_id,
            is_dismiss=False,
        )
    except Exception:
        logger.exception(f"自动退出群 {group_id} 失败")
        return

    logger.info(f"群 {group_id} 当前人数为 {member_count}，已自动退群")


async def _notify_group_join(bot: Bot, group_id: int) -> None:
    """向非白名单新群提示权限限制，并按当前人数提示自动退群。"""
    try:
        await bot.call_api(
            "send_group_msg",
            group_id=group_id,
            message="此群聊不在白名单中，指令无法使用，请联系事务所负责人（机器人创建者）",
        )
    except Exception:
        logger.exception(f"向群 {group_id} 发送白名单提示失败")

    try:
        group_info = await bot.call_api(
            "get_group_info", group_id=group_id, no_cache=True
        )
        member_count = int(group_info["member_count"])
        if should_auto_leave_group(member_count):
            reason = (
                "过少" if member_count < config.auto_leave_group_min_members else "过多"
            )
            await bot.call_api(
                "send_group_msg",
                group_id=group_id,
                message=(
                    f"此群聊人数{reason}，将在{AUTO_LEAVE_DELAY_SECONDS // 60}分钟后自动退群，"
                    "如有疑问请联系事务所负责人"
                ),
            )
    except Exception:
        logger.exception(f"检查群 {group_id} 人数或发送退群提示失败")


def schedule_auto_leave_group(bot: Bot, group_id: int) -> None:
    """为非白名单新群安排一次入群提示和延迟退群检查。"""
    if is_group_whitelisted(group_id):
        return

    task_key = (int(bot.self_id), int(group_id))
    current_task = _leave_tasks.get(task_key)
    if current_task is not None and not current_task.done():
        return

    task = asyncio.create_task(
        _leave_group_after_delay(bot, int(group_id)),
        name=f"auto-leave-group-{group_id}",
    )
    _leave_tasks[task_key] = task

    def _remove_finished_task(finished_task: asyncio.Task[None]) -> None:
        """移除已结束的退群检查任务。"""
        if _leave_tasks.get(task_key) is finished_task:
            _leave_tasks.pop(task_key, None)

    task.add_done_callback(_remove_finished_task)
    logger.info(
        f"群 {group_id} 不在白名单中，将在 "
        f"{AUTO_LEAVE_DELAY_SECONDS // 60} 分钟后检查并自动退群"
    )


auto_leave_group_notice = on_notice()


@auto_leave_group_notice.handle()
async def _handle_group_increase(bot: Bot, event: GroupIncreaseNoticeEvent):
    """仅在机器人自身入群时安排提示和群规模检查。"""
    if event.user_id == event.self_id:
        schedule_auto_leave_group(bot, event.group_id)
