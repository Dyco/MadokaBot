"""每日投胎卡片与世界地图渲染。"""

import asyncio
import json
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from nonebot.adapters.onebot.v11 import MessageSegment
from nonebot_plugin_htmlrender import html_to_pic

from madokabot.core.resources import ResourceFolder, ResourceType, get_file
from .simulation import DATA_DIR

TEMPLATE_DIR = Path(__file__).parent / "templates"
_environment = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR), encoding="utf-8"),
    autoescape=select_autoescape(("html", "xml")),
    undefined=StrictUndefined,
)
_render_limit = asyncio.Semaphore(2)


@lru_cache(maxsize=1)
def load_world_map() -> list[dict]:
    """读取离线地图路径，台湾、香港、澳门与中国共用高亮编号。"""
    return json.loads((DATA_DIR / "world_map.json").read_text(encoding="utf-8"))["regions"]


def render_reborn_html(result: dict, name: str) -> str:
    """生成无需外部网络资源的投胎卡片页面。"""
    font = get_file(ResourceType.FONT, ResourceFolder.SIGN, "font.ttf")
    country = result["country"]
    return _environment.get_template("reborn.html").render(
        result=result,
        name=name,
        regions=load_world_map(),
        marker_x=(country["longitude"] + 180) * 1000 / 360,
        marker_y=(85 - country["latitude"]) * 1000 / 360,
        font_uri=font.resolve().as_uri() if font else "",
        probability=f"{result['probability'] * 100:.4f}%",
        births=f"{country['births']:,.0f}",
    )


async def render_reborn_card(result: dict, name: str) -> MessageSegment:
    """使用公共浏览器渲染能力生成 PNG 图片消息。"""
    async with _render_limit:
        picture = await html_to_pic(
            html=render_reborn_html(result, name),
            template_path=TEMPLATE_DIR.resolve().as_uri(),
            viewport={"width": 1080, "height": 10},
            full_page=True,
        )
    return MessageSegment.image(picture)


def result_text(result: dict, *, prefix: str) -> str:
    """图片不可用时返回完整文字结果及本次操作提示，包括重开的扣款信息。"""
    country = result["country"]
    attributes = " / ".join(f"{name} {value}" for name, value in result["attributes"].items())
    return (
        f"{prefix}\n每日投胎 · {result['date']}\n"
        f"出生地：{country['name']}\n性别：{result['gender']}\n"
        f"抽中概率：{result['probability']:.4%}\n"
        f"{attributes}\n综合评分：{result['score']}/100 · {result['label']}\n"
        f"{result['comment']}\n"
        f"人口数据：{result['source']} / {result['data_year']} 年中方案预测\n"
        "属性与评分为随机游戏设定。上海时间明日零点可再次免费投胎。"
    )
