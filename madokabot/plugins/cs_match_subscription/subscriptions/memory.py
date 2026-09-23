"""赛事通知的短期去重记忆。"""

from __future__ import annotations

from time import monotonic

NOTIFICATION_MEMORY_TTL = 24 * 60 * 60


notification_memory: dict[tuple[str, str], float] = {}


def cleanup_notification_memory() -> None:
    """清理短期推送幂等记忆，避免长期运行时无限增长。"""
    deadline = monotonic() - NOTIFICATION_MEMORY_TTL
    expired = [
        key for key, created_at in notification_memory.items() if created_at < deadline
    ]
    for key in expired:
        notification_memory.pop(key, None)


def notification_memory_key(match_id: str, notification: str) -> tuple[str, str]:
    """组合比赛编号与通知类型，生成去重键。"""
    return str(match_id), notification


def notification_was_seen(match_id: str, notification: str) -> bool:
    """读取短期推送记忆。"""
    cleanup_notification_memory()
    return notification_memory_key(match_id, notification) in notification_memory


def remember_notification(match_id: str, notification: str) -> None:
    """记录已经生成过的推送事件。"""
    cleanup_notification_memory()
    notification_memory[notification_memory_key(match_id, notification)] = monotonic()


def clear_notification_memory(match_id: str) -> None:
    """清理指定比赛的短期推送记忆。"""
    match_key = str(match_id)
    for key in tuple(notification_memory):
        if key[0] == match_key:
            notification_memory.pop(key, None)
