"""Resolver 支持内容与群组开关状态展示。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape
from nonebot.adapters.onebot.v11 import MessageSegment
from nonebot_plugin_htmlrender import html_to_pic

from .state import (
    CONTENT_KEYS,
    RESOLVER_KEYS,
    is_content_enabled,
    is_resolver_enabled,
)

TEMPLATE_DIR = Path(__file__).parent / "templates"
STATUS_TEMPLATE_NAME = "resolver_status.html"
STATUS_COLUMNS = (
    ("video", "视频"),
    ("audio", "音频"),
    ("image", "图片"),
    ("text", "文本"),
    ("comment", "评论"),
)

# 各平台当前代码实际可以发送的内容类型。
RESOLVER_CAPABILITIES = {
    "bilibili": frozenset({"video", "image", "text", "comment"}),
    "douyin": frozenset({"video", "image", "text", "comment"}),
    "tiktok": frozenset({"video", "text"}),
    "acfun": frozenset({"video", "text"}),
    "twitter": frozenset({"video", "image", "text"}),
    "xiaohongshu": frozenset({"video", "image", "text"}),
    "youtube": frozenset({"video", "text"}),
    "netease": frozenset({"audio", "image", "text"}),
    "kugou": frozenset({"audio", "image", "text"}),
    "weibo": frozenset({"video", "image", "text"}),
}
# 表格中的平台名称、徽标文字与主题色。
RESOLVER_DISPLAY = {
    "bilibili": ("B站", "B", "bilibili"),
    "douyin": ("抖音", "DY", "douyin"),
    "tiktok": ("TikTok", "TK", "tiktok"),
    "acfun": ("ACFun", "A", "acfun"),
    "twitter": ("X / Twitter", "X", "twitter"),
    "xiaohongshu": ("小红书", "小红书", "xiaohongshu"),
    "youtube": ("YouTube", "YT", "youtube"),
    "netease": ("网易云音乐", "N", "netease"),
    "kugou": ("酷狗音乐", "KG", "kugou"),
    "weibo": ("微博", "WB", "weibo"),
}
# 全局配置中可填写的平台处理器名称。
RESOLVER_HANDLER_NAMES = {
    "bilibili": frozenset({"bilibili"}),
    "douyin": frozenset({"dy", "douyin"}),
    "tiktok": frozenset({"tiktok"}),
    "acfun": frozenset({"ac", "acfun"}),
    "twitter": frozenset({"twitter"}),
    "xiaohongshu": frozenset({"xiaohongshu"}),
    "youtube": frozenset({"youtube"}),
    "netease": frozenset({"netease"}),
    "kugou": frozenset({"kugou"}),
    "weibo": frozenset({"wb", "weibo"}),
}
_template_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(("html", "xml")),
)
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def _status_item(
    target_id: int | str | None,
    resolver_key: str,
    content_key: str,
    globally_enabled: bool,
) -> dict[str, str]:
    """生成单个平台单项内容的展示状态。"""
    if content_key not in RESOLVER_CAPABILITIES[resolver_key]:
        return {"label": "不支持", "kind": "unsupported"}

    enabled = globally_enabled and is_resolver_enabled(target_id, resolver_key)
    if enabled and content_key in CONTENT_KEYS:
        enabled = is_content_enabled(target_id, resolver_key, content_key)
    return {
        "label": "打开" if enabled else "关闭",
        "kind": "enabled" if enabled else "disabled",
    }


def build_status_context(
    target_id: int | str | None,
    scope_name: str,
    globally_disabled: set[str] | None = None,
) -> dict[str, object]:
    """构造 Resolver 状态表的模板数据。"""
    globally_disabled = globally_disabled or set()
    rows = []
    for resolver_key in RESOLVER_KEYS:
        display_name, logo_text, logo_class = RESOLVER_DISPLAY[resolver_key]
        globally_enabled = RESOLVER_HANDLER_NAMES[resolver_key].isdisjoint(
            globally_disabled
        )
        rows.append(
            {
                "key": resolver_key,
                "name": display_name,
                "logo": logo_text,
                "logo_class": logo_class,
                "statuses": [
                    _status_item(
                        target_id,
                        resolver_key,
                        content_key,
                        globally_enabled,
                    )
                    for content_key, _ in STATUS_COLUMNS
                ],
            }
        )
    return {
        "scope_name": scope_name,
        "updated_at": datetime.now(_SHANGHAI_TZ).strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "columns": [label for _, label in STATUS_COLUMNS],
        "rows": rows,
    }


async def render_resolver_status_card(
    target_id: int | str | None,
    scope_name: str,
    globally_disabled: set[str] | None = None,
) -> MessageSegment:
    """通过 html_to_pic 将 Resolver 状态表渲染为图片消息。"""
    template = _template_env.get_template(STATUS_TEMPLATE_NAME)
    html = template.render(
        **build_status_context(target_id, scope_name, globally_disabled)
    )
    image_bytes = await html_to_pic(
        html=html,
        viewport={"width": 1080, "height": 100},
        device_scale_factor=1,
        full_page=True,
    )
    return MessageSegment.image(image_bytes)
