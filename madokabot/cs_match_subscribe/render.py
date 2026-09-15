"""Rating 3.0 HTML 生成与 Playwright 渲染。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from nonebot.adapters.onebot.v11 import MessageSegment
from nonebot_plugin_htmlrender import html_to_pic

from .config import config
from .models import EventData, MatchData


TEMPLATE_DIR = Path(__file__).parent / "templates"
HTML_FILE_PATH = TEMPLATE_DIR / "rating.html"
EVENT_HTML_FILE_PATH = TEMPLATE_DIR / "event_list.html"
_template_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(("html", "xml")),
)


def render_rating_html(match: MatchData, *, map_name: str | None = None) -> str:
    """把赛事数据渲染为可独立打开的 rating.html 内容。"""
    template = _template_env.get_template(HTML_FILE_PATH.name)
    return template.render(
        **match.to_template_context(
            show_player_photos=config.cs_rating_show_player_photos,
            map_name=map_name,
        )
    )


async def render_rating_card(
    match: MatchData,
    *,
    map_name: str | None = None,
) -> MessageSegment:
    """通过 nonebot-plugin-htmlrender（Playwright）生成 QQ 图片消息。"""
    html = render_rating_html(match, map_name=map_name)
    image_bytes = await html_to_pic(
        html=html,
        template_path=HTML_FILE_PATH.parent.resolve().as_uri(),
        viewport={"width": config.cs_rating_width, "height": 10},
        device_scale_factor=config.cs_rating_device_scale_factor,
        full_page=True,
    )
    return MessageSegment.image(image_bytes)


def _event_is_ongoing(event: EventData, now: datetime) -> bool:
    """判断赛事当前是否正在进行。"""
    return event.start_at is not None and event.start_at <= now and (
        event.end_at is None or event.end_at >= now
    )


def _event_sections(
    events: list[EventData],
    *,
    now: datetime | None = None,
) -> list[dict[str, object]]:
    """按正在进行和赛事开始月份组织赛事卡片。"""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)

    ongoing: list[EventData] = []
    by_month: dict[tuple[int, int], list[EventData]] = {}
    for event in events:
        if _event_is_ongoing(event, current):
            ongoing.append(event)
        elif event.start_at is not None:
            by_month.setdefault((event.start_at.year, event.start_at.month), []).append(event)

    sections: list[dict[str, object]] = []
    if ongoing:
        sections.append({"title": "正在进行", "events": ongoing})
    for (year, month), month_events in sorted(by_month.items()):
        sections.append({"title": f"{year}年{month}月 赛事", "events": month_events})
    return sections


def render_event_list_html(
    events: list[EventData],
    *,
    now: datetime | None = None,
) -> str:
    """把赛事列表渲染为可独立打开的赛事卡片 HTML。"""
    template = _template_env.get_template(EVENT_HTML_FILE_PATH.name)
    return template.render(sections=_event_sections(events, now=now))


async def render_event_list_card(events: list[EventData]) -> MessageSegment:
    """通过 Playwright 将赛事卡片列表生成 QQ 图片消息。"""
    html = render_event_list_html(events)
    image_bytes = await html_to_pic(
        html=html,
        template_path=TEMPLATE_DIR.resolve().as_uri(),
        viewport={"width": config.cs_rating_width, "height": 10},
        device_scale_factor=config.cs_rating_device_scale_factor,
        full_page=True,
    )
    return MessageSegment.image(image_bytes)

