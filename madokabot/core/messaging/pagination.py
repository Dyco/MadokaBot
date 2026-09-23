"""回复分页的输入解析与消息编号提取。"""

import re
from typing import Any


def parse_page_command(
    text: str,
    current_page: int,
    total_pages: int,
) -> tuple[int | None, bool]:
    """解析翻页回复，返回目标页码及是否超出范围。"""
    normalized = text.strip().lower()
    if not normalized:
        return None, False

    if normalized in {"下一页", "下页", "next", "n"}:
        return min(total_pages, current_page + 1), False
    if normalized in {"上一页", "上页", "prev", "previous", "p"}:
        return max(1, current_page - 1), False

    page_match = re.fullmatch(r"第?\s*(\d+)\s*页?", normalized)
    if page_match:
        page = int(page_match.group(1))
        if 1 <= page <= total_pages:
            return page, False
        return None, True
    return None, False


def extract_message_id(send_result: Any) -> int | None:
    """从消息发送结果中提取回复分页所需的消息编号。"""
    if hasattr(send_result, "msg_ids"):
        msg_ids = getattr(send_result, "msg_ids", None) or []
        if msg_ids:
            first_id = msg_ids[0]
            if isinstance(first_id, dict):
                first_id = first_id.get("message_id")
            try:
                return int(first_id) if first_id is not None else None
            except (TypeError, ValueError):
                return None

    if isinstance(send_result, dict):
        message_id = send_result.get("message_id")
    else:
        message_id = getattr(send_result, "message_id", None)
    try:
        return int(message_id) if message_id is not None else None
    except (TypeError, ValueError):
        return None
