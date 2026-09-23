"""RSS 上传项完成后的记录收尾。"""

from typing import Any, Dict

from nonebot.adapters.onebot.v11 import Bot

from ..download_notices import _safe_upload_notice
from ..download_records import _save_upload_record
from ..download_state import DownloadStatus, _clear_download_tracking


async def _finish_upload_record_if_complete(
    bot: Bot, gid: str, record: Dict[str, Any]
) -> bool:
    """全部文件完成后保存记录并发送完成通知。"""
    items = record.get("upload_items")
    if not isinstance(items, list) or not items:
        return False
    valid_items = [item for item in items if isinstance(item, dict)]
    if not valid_items:
        return False
    if not all(
        str(item.get("status")) == DownloadStatus.UPLOAD_COMPLETE.value
        for item in valid_items
    ):
        return False
    _save_upload_record(gid, record)
    _clear_download_tracking(gid)
    message = (
        f"✅ {record.get('name', '下载任务')}\nGID：{gid}\n全部文件均已确认发送成功。"
    )
    group_ids = sorted(
        {
            str(item.get("group_id"))
            for item in items
            if isinstance(item, dict) and item.get("group_id")
        }
    )
    for group_id in group_ids:
        await _safe_upload_notice(bot, message, group_id)
    return True
