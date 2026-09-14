"""Rating 3.0 HTML 生成与 Playwright 渲染。"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from nonebot.adapters.onebot.v11 import MessageSegment
from nonebot_plugin_htmlrender import html_to_pic

from .config import config
from .models import MatchData


HTML_FILE_PATH = Path(__file__).parent / "rating.html"
_template_env = Environment(
    loader=FileSystemLoader(str(HTML_FILE_PATH.parent)),
    autoescape=select_autoescape(("html", "xml")),
)


def render_rating_html(match: MatchData) -> str:
    """把赛事数据渲染为可独立打开的 rating.html 内容。"""
    template = _template_env.get_template(HTML_FILE_PATH.name)
    return template.render(
        **match.to_template_context(
            show_player_photos=config.cs_rating_show_player_photos,
        )
    )


async def render_rating_card(match: MatchData) -> MessageSegment:
    """通过 nonebot-plugin-htmlrender（Playwright）生成 QQ 图片消息。"""
    html = render_rating_html(match)
    image_bytes = await html_to_pic(
        html=html,
        template_path=HTML_FILE_PATH.parent.resolve().as_uri(),
        viewport={"width": config.cs_rating_width, "height": 10},
        device_scale_factor=config.cs_rating_device_scale_factor,
        full_page=True,
    )
    return MessageSegment.image(image_bytes)

