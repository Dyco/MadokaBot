"""根据群成员数量自动退出群聊。"""

import asyncio

from nonebot import logger, on_notice
from nonebot.adapters.onebot.v11 import Bot, GroupIncreaseNoticeEvent

from .config import config
from .group_list import is_group_whitelisted


AUTO_LEAVE_DELAY_SECONDS = 3 * 60
_leave_tasks: dict[tuple[int, int], asyncio.Task[None]] = {}


def should_auto_leave_group(member_count: int) -> bool:
    """判断群人数是否命中自动退群条件。"""
    return (
        member_count < config.auto_leave_group_min_members
        or member_count > config.auto_leave_group_max_members
    )


async def _leave_group_after_delay(bot: Bot, group_id: int) -> None:
    await asyncio.sleep(AUTO_LEAVE_DELAY_SECONDS)

    if is_group_whitelisted(group_id):
        logger.info(f"群 {group_id} 已加入白名单，取消自动退群")
        return

    try:
        group_info = await bot.call_api("get_group_info", group_id=group_id)
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


def schedule_auto_leave_group(bot: Bot, group_id: int) -> None:
    """为机器人刚加入的群聊安排延迟退群任务。"""
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
    if event.user_id == event.self_id:
        schedule_auto_leave_group(bot, event.group_id)
