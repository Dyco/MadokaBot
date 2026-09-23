"""RSS 群文件上传结果的延迟核验。"""

from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from nonebot.adapters.onebot.v11 import Bot
from nonebot.log import logger
from nonebot_plugin_apscheduler import scheduler

from madokabot.core.messaging.media import media_delivery

from ..config import config
from ..download_notices import _safe_upload_notice
from ..download_records import (
    _find_upload_item,
    _now_iso,
    _save_upload_record,
    download_records,
)
from ..download_state import DownloadStatus
from ..download_validation import _int_value
from ..utils import get_bot
from .completion import _finish_upload_record_if_complete


def _verification_job_id(gid: str, item_id: str) -> str:
    """生成稳定的上传核验任务编号。"""
    return f"rss-upload-verify-{gid}-{item_id}"


def _parse_record_time(value: Any) -> Optional[datetime]:
    """解析上传记录中保存的时间。"""
    if not value:
        return None
    try:
        result = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if result.tzinfo is None:
        result = result.astimezone()
    return result


def _upload_verify_delay_text() -> str:
    """生成上传核验延迟的提示文本。"""
    seconds = int(config.rss_upload_verify_delay)
    if seconds % 3600 == 0:
        return f"{seconds // 3600} 小时"
    if seconds % 60 == 0:
        return f"{seconds // 60} 分钟"
    return f"{seconds} 秒"


def _schedule_upload_verification(
    gid: str,
    item: Dict[str, Any],
    run_at: Optional[datetime] = None,
) -> None:
    """按原任务编号安排群文件核验。"""
    item_id = str(item["id"])
    run_at = run_at or _parse_record_time(item.get("next_verify_at"))
    run_at = run_at or (
        datetime.now().astimezone()
        + timedelta(seconds=int(config.rss_upload_verify_delay))
    )
    item["next_verify_at"] = run_at.isoformat()
    scheduler.add_job(
        func=verify_uploaded_file,
        trigger="date",
        run_date=run_at,
        args=(gid, item_id),
        id=_verification_job_id(gid, item_id),
        misfire_grace_time=86400,
        replace_existing=True,
    )


async def verify_uploaded_file(gid: str, item_id: str) -> None:
    """核对群文件是否已上传成功并更新记录。"""
    record = download_records.get(gid)
    if not record or not (item := _find_upload_item(record, item_id)):
        return
    if str(item.get("status")) != DownloadStatus.UPLOAD_VERIFYING.value:
        return

    async def handle_verification_error(
        message: str,
        bot: Optional[Bot],
    ) -> None:
        error_count = _int_value(item.get("verification_error_count")) + 1
        item["verification_error_count"] = error_count
        item["last_error"] = message
        item["status"] = DownloadStatus.UPLOAD_FAILED.value
        item["upload_success"] = False
        item["verified_at"] = _now_iso()
        item["next_verify_at"] = None
        _save_upload_record(gid, record)
        if bot is not None:
            await _safe_upload_notice(
                bot,
                f"❌ {record.get('name', '下载任务')}\nGID：{gid}\n"
                f"群文件核验失败：{item.get('file_name')}\n"
                f"原因：{message}\n已停止自动处理，"
                f"可使用 /RSS 重试 {gid}。",
                str(item.get("group_id")),
            )

    bot = await get_bot()
    if bot is None:
        await handle_verification_error("当前没有可用的 Bot", None)
        return

    group_id = str(item.get("group_id"))
    try:
        remote_file = await media_delivery.find_same_group_file(
            bot,
            group_id,
            str(item.get("file_name") or ""),
            _int_value(item.get("file_size")),
            str(item.get("folder_id") or "/"),
        )
    except Exception as exc:
        message = f"群文件核验失败：{type(exc).__name__}: {exc}"
        await handle_verification_error(message, bot)
        logger.warning(f"群文件核验请求失败[{gid}][{item_id}]：{exc}")
        return

    item["verification_error_count"] = 0
    if remote_file:
        item["status"] = DownloadStatus.UPLOAD_COMPLETE.value
        item["upload_success"] = True
        item["remote_file_id"] = remote_file.get("file_id")
        item["verified_at"] = _now_iso()
        item["next_verify_at"] = None
        item["last_error"] = None
        _save_upload_record(gid, record)
        completed = await _finish_upload_record_if_complete(bot, gid, record)
        if not completed:
            await _safe_upload_notice(
                bot,
                f"✅ {record.get('name', '下载任务')}\nGID：{gid}\n"
                f"已确认群文件上传成功：{item.get('file_name')}",
                group_id,
            )
        return

    item["status"] = DownloadStatus.UPLOAD_FAILED.value
    item["upload_success"] = False
    item["verified_at"] = _now_iso()
    item["next_verify_at"] = None
    item["last_error"] = "群文件中未找到同名且同大小的文件"
    _save_upload_record(gid, record)
    await _safe_upload_notice(
        bot,
        f"❌ {record.get('name', '下载任务')}\nGID：{gid}\n"
        f"群文件上传未成功：{item.get('file_name')}\n"
        f"文件会保留等待定期清理，"
        f"可使用 /RSS 重试 {gid}。",
        group_id,
    )
