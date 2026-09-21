"""Rating 3.0 HTML 生成与 Playwright 渲染。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from nonebot.adapters.onebot.v11 import MessageSegment
from nonebot_plugin_htmlrender import html_to_pic as _html_to_pic

from .assets import fetch_image_data_url
from .config import config
from .constants import event_font_context, font_context
from .models import EventData, MatchData


TEMPLATE_DIR = Path(__file__).parent / "templates"
HTML_FILE_PATH = TEMPLATE_DIR / "rating.html"
EVENT_HTML_FILE_PATH = TEMPLATE_DIR / "event_list.html"
PREDICTION_RANK_HTML_FILE_PATH = TEMPLATE_DIR / "prediction_rank.html"
STATS_TEMPLATE_1_HTML_FILE_PATH = TEMPLATE_DIR / "stats_template_1.html"
STATS_TEMPLATE_2_HTML_FILE_PATH = TEMPLATE_DIR / "stats_template_2.html"
_template_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(("html", "xml")),
)
_stats_template_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(("html", "xml")),
    undefined=StrictUndefined,
)
_RENDER_SEMAPHORE = asyncio.Semaphore(1)


async def html_to_pic(**kwargs) -> bytes:
    """限制本插件的并发截图，避免多条指令同时创建高分辨率页面。"""
    async with _RENDER_SEMAPHORE:
        return await _html_to_pic(**kwargs)


def render_rating_html(match: MatchData, *, map_name: str | None = None) -> str:
    """把赛事数据渲染为可独立打开的 rating.html 内容。"""
    template = _template_env.get_template(HTML_FILE_PATH.name)
    context = match.to_template_context(
        map_name=map_name,
    )
    context.update(font_context())
    return template.render(**context)


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
    context = event_font_context()
    context["sections"] = _event_sections(events, now=now)
    return template.render(**context)


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


def render_prediction_rank_html(
    entries: list[dict[str, object]],
    *,
    scope_label: str,
) -> str:
    """生成竞猜排行榜 HTML。"""
    template = _template_env.get_template(PREDICTION_RANK_HTML_FILE_PATH.name)
    context = font_context()
    context.update({"entries": entries, "scope_label": scope_label})
    return template.render(**context)


async def render_prediction_rank_card(
    entries: list[dict[str, object]],
    *,
    scope_label: str,
) -> MessageSegment:
    """将竞猜排行榜渲染为图片消息。"""
    avatar_sources = await asyncio.gather(
        *(
            fetch_image_data_url(str(entry.get("avatar_url") or ""))
            for entry in entries
        )
    )
    prepared_entries: list[dict[str, object]] = []
    for entry, avatar_src in zip(entries, avatar_sources):
        prepared = dict(entry)
        prepared["avatar_src"] = avatar_src
        prepared_entries.append(prepared)

    image_bytes = await html_to_pic(
        html=render_prediction_rank_html(
            prepared_entries,
            scope_label=scope_label,
        ),
        template_path=TEMPLATE_DIR.resolve().as_uri(),
        viewport={"width": config.cs_stats_width, "height": 10},
        device_scale_factor=config.cs_rating_device_scale_factor,
        full_page=True,
    )
    return MessageSegment.image(image_bytes)


def render_player_stats_html(data: dict[str, object]) -> str:
    """渲染已经由平台适配器标准化的玩家战绩。"""
    context = dict(data)
    context.setdefault("avatar_src", "")
    context["template2_width"] = config.cs_stats_template_2_width
    context.update(font_context())
    template_file = (
        STATS_TEMPLATE_2_HTML_FILE_PATH
        if config.cs_stats_template == 2
        else STATS_TEMPLATE_1_HTML_FILE_PATH
    )
    template = _stats_template_env.get_template(template_file.name)
    return template.render(**context)


async def render_player_stats_card(data: dict[str, object]) -> MessageSegment:
    """通过 Playwright 把平台战绩卡片渲染为 QQ 图片。"""
    context = dict(data)
    context["avatar_src"] = await fetch_image_data_url(str(data.get("avatar_url") or ""))
    stats_width = (
        config.cs_stats_template_2_width
        if config.cs_stats_template == 2
        else config.cs_stats_width
    )
    image_bytes = await html_to_pic(
        html=render_player_stats_html(context),
        template_path=TEMPLATE_DIR.resolve().as_uri(),
        viewport={"width": stats_width, "height": 10},
        device_scale_factor=config.cs_rating_device_scale_factor,
        full_page=True,
    )
    return MessageSegment.image(image_bytes)

