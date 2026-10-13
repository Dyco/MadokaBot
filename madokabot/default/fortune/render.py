"""运势卡片模板与上半身立绘渲染。"""

import asyncio
import base64
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from nonebot.adapters.onebot.v11 import MessageSegment
from nonebot_plugin_datastore import create_session
from nonebot_plugin_htmlrender import html_to_pic
from PIL import Image

from madokabot.core.resources import ResourceFolder, ResourceType, get_file
from madokabot.core.user.models import UserStats
from madokabot.core.version import get_bot_version
from madokabot.default.account.config import config as account_config
from madokabot.default.shop.catalog import get_skin_path

from .service import FortuneResult

TEMPLATE_DIR = Path(__file__).parent / "templates"
_environment = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR), encoding="utf-8"),
    autoescape=select_autoescape(("html",)),
    undefined=StrictUndefined,
)
_render_limit = asyncio.Semaphore(2)


def render_fortune_html(result: FortuneResult, name: str, skin_asset: str) -> str:
    """按立绘可见范围定位上半身，复用本地字体与实际版本号生成卡片。"""
    skin = get_skin_path(skin_asset) or get_skin_path(account_config.initial_chara)
    skin_uri = ""
    skin_height = 680.0
    skin_top = 8.0
    if skin is not None:
        skin_uri = "data:image/png;base64," + base64.b64encode(skin.read_bytes()).decode("ascii")
        with Image.open(skin) as image:
            bounds = image.convert("RGBA").getchannel("A").getbbox()
            if bounds is not None:
                scale = skin_height / (bounds[3] - bounds[1])
                skin_height = round(image.height * scale, 2)
                skin_top = round(skin_top - bounds[1] * scale, 2)
    font = get_file(ResourceType.FONT, ResourceFolder.SIGN, "font.ttf")
    title_font = get_file(ResourceType.FONT, ResourceFolder.SIGN, "NotoSerifSC-Black.otf")
    return _environment.get_template("fortune.html").render(
        result=result,
        name=name,
        bot_version=get_bot_version(),
        skin_uri=skin_uri,
        skin_height=skin_height,
        skin_top=skin_top,
        font_uri=font.resolve().as_uri() if font else "",
        title_font_uri=title_font.resolve().as_uri() if title_font else "",
    )


async def render_fortune_card(result: FortuneResult, uid: str, name: str) -> MessageSegment:
    """读取已注册账号的立绘及显示名，生成640×360的紧凑运势卡片。"""
    async with create_session() as session:
        user = await session.get(UserStats, uid)
        if user is None:
            raise LookupError("用户未注册")
        skin_asset = user.skin_asset
        name = user.display_name or name
    async with _render_limit:
        picture = await html_to_pic(
            html=render_fortune_html(result, name, skin_asset),
            template_path=TEMPLATE_DIR.resolve().as_uri(),
            viewport={"width": 640, "height": 360},
            full_page=False,
        )
    return MessageSegment.image(picture)
