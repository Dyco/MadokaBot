from __future__ import annotations

from pathlib import Path

from nonebot import __version__ as nonebot_version
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from nonebot.adapters.onebot.v11 import MessageSegment
from nonebot_plugin_htmlrender import html_to_pic

from ...constants import ResType, SubFolder
from ...utils import get_file
from .service import PreparedImage

TEMPLATE_DIR = Path(__file__).parent / "templates"
TEMPLATE_FILES = {
    "1": "trackpic.html",
    "2": "template_2.html",
    "3": "template_3.html",
    "4": "template_4.html",
}
VIEWPORTS = {
    "1": {"width": 1320, "height": 2868},
    "2": {"width": 1080, "height": 1920},
    "3": {"width": 1080, "height": 1920},
    "4": {"width": 1080, "height": 1920},
}

_template_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(("html", "xml")),
    undefined=StrictUndefined,
)


def normalize_template_id(value: str | None) -> str:
    """将用户输入转换为已注册的模板编号。"""
    template_id = (value or "1").strip().casefold()
    if template_id.startswith("模板"):
        template_id = template_id[2:]
    if template_id.startswith("template"):
        template_id = template_id[8:]
    if template_id not in TEMPLATE_FILES:
        raise ValueError("模板编号必须是 1、2、3 或 4")
    return template_id


def _font_uri() -> str:
    """获取现有资源目录中的中文字体。"""
    font_path = get_file(
        ResType.FONT,
        SubFolder.CS,
        "SourceHanSansSC-VF.ttf.woff2",
    )
    return font_path.resolve().as_uri() if font_path is not None else ""


async def render_music_card(
    image: PreparedImage,
    template_id: str,
    *,
    title: str,
    subtitle: str,
    author: str,
    user_id: str,
) -> MessageSegment:
    """使用指定音乐模板渲染图片消息。"""
    template_id = normalize_template_id(template_id)
    template_name = TEMPLATE_FILES[template_id]
    template = _template_env.get_template(template_name)
    html = template.render(
        image_data_url=image.data_url,
        palette=list(image.palette),
        title=title,
        subtitle=subtitle,
        author=author,
        user_id=user_id,
        signature=f"MadokaBot v{nonebot_version or 'unknown'}",
        font_path=_font_uri(),
        theme_class=f"theme-{template_id}",
    )
    image_bytes = await html_to_pic(
        html=html,
        template_path=TEMPLATE_DIR.resolve().as_uri(),
        viewport=VIEWPORTS[template_id],
    )
    return MessageSegment.image(image_bytes)
