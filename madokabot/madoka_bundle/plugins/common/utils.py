import re


def parse_page_command(
    text: str,
    current_page: int,
    total_pages: int,
) -> tuple[int | None, bool]:
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
