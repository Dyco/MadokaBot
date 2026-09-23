"""RSS 重启后的上传队列与核验任务恢复。"""

from datetime import datetime, timedelta

from nonebot.adapters.onebot.v11 import Bot
from nonebot.log import logger

from madokabot.core.messaging.media import MediaDeliveryMode

from ..config import config
from ..download_records import (
    _migrate_legacy_upload_items,
    _save_upload_record,
    _upload_item_id,
    download_records,
)
from ..download_state import DownloadStatus
from .queue import _enqueue_upload_item
from .verification import _parse_record_time, _schedule_upload_verification


async def restore_upload_records(_: Bot) -> None:
    """恢复重启前尚未完成的上传和核验任务。"""
    restored_queue = 0
    restored_verifications = 0
    now = datetime.now().astimezone()
    for gid, record in list(download_records.items()):
        items = _migrate_legacy_upload_items(gid, record)
        if not items:
            continue
        for item in items:
            item_id = str(item.get("id") or "")
            if not item_id:
                item_id = _upload_item_id(
                    gid,
                    str(item.get("group_id") or ""),
                    str(item.get("local_path") or ""),
                )
                item["id"] = item_id
            status = str(item.get("status") or "")
            if status == DownloadStatus.UPLOAD_QUEUED.value:
                _enqueue_upload_item(gid, item_id)
                restored_queue += 1
            elif status == DownloadStatus.UPLOADING.value:
                if str(item.get("delivery_mode")) in {
                    MediaDeliveryMode.VIDEO_MESSAGE.value,
                    MediaDeliveryMode.VIDEO_COMPRESS.value,
                }:
                    item["status"] = DownloadStatus.UPLOAD_QUEUED.value
                    _enqueue_upload_item(gid, item_id)
                    restored_queue += 1
                    continue
                item["status"] = DownloadStatus.UPLOAD_VERIFYING.value
                last_attempt = _parse_record_time(item.get("last_attempt_at"))
                run_at = (
                    last_attempt
                    + timedelta(seconds=int(config.rss_upload_verify_delay))
                    if last_attempt
                    else now
                )
                _schedule_upload_verification(gid, item, max(run_at, now))
                restored_verifications += 1
            elif status == DownloadStatus.UPLOAD_VERIFYING.value:
                run_at = _parse_record_time(item.get("next_verify_at")) or now
                _schedule_upload_verification(gid, item, max(run_at, now))
                restored_verifications += 1
        _save_upload_record(gid, record)
    if restored_queue or restored_verifications:
        logger.info(
            f"已恢复群文件任务：上传队列 {restored_queue} 个，"
            f"等待核验 {restored_verifications} 个"
        )
