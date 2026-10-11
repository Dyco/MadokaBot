"""每日投胎卡片与世界地图渲染。"""

import asyncio
import json
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from nonebot.adapters.onebot.v11 import MessageSegment
from nonebot_plugin_htmlrender import html_to_pic

from madokabot.core.resources import ResourceFolder, ResourceType, get_file
from .attributes import attribute_rows
from .simulation import DATA_DIR, display_result

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


@lru_cache(maxsize=1)
def load_china_map() -> dict:
    """读取省级 SVG 路径、南海诸岛附图及港澳局部放大图。"""
    return json.loads((DATA_DIR / "china_map.json").read_text(encoding="utf-8"))


def render_reborn_html(result: dict, name: str) -> str:
    """生成无需外部网络资源的星级卡片，并兼容旧百分制记录。"""
    result = display_result(result)
    font = get_file(ResourceType.FONT, ResourceFolder.SIGN, "font.ttf")
    country = result["country"]
    china = result.get("mode") == "china"
    china_map = load_china_map() if china else {}
    region = next(row for row in china_map["regions"] if row["code"] == country["code"]) if china else None
    rows = attribute_rows(result["attributes"])
    return _environment.get_template("reborn.html").render(
        result=result,
        attribute_rows=rows,
        name=name,
        china=china,
        china_map=china_map,
        regions=[] if china else load_world_map(),
        marker_x=region["marker_x"] if china else (country["longitude"] + 180) * 1000 / 360,
        marker_y=region["marker_y"] if china else (85 - country["latitude"]) * 1000 / 360,
        font_uri=font.resolve().as_uri() if font else "",
        probability=f"{result['probability'] * 100:.4f}%",
        births=("约 " if country.get("births_estimated") else "") + f"{country['births']:,.0f}",
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
    """图片不可用时返回出生信息、星级、潜力评分及本次扣款信息。"""
    result = display_result(result)
    country = result["country"]
    attributes = "\n".join(
        f"{row['name']}：{row['value_text']} 星（{row['title']}）"
        for row in attribute_rows(result["attributes"])
    )
    title = "投胎中国" if result.get("mode") == "china" else "每日投胎"
    note = result.get("data_note", "中方案预测")
    return (
        f"{prefix}\n{title} · {result['date']}\n"
        f"出生地：{country['name']}\n性别：{result['gender']}\n"
        f"抽中概率：{result['probability']:.4%}\n"
        f"{attributes}\n综合潜力：{result['score']}/100 · {result['label']}\n"
        f"人口数据：{result['source']} / {result['data_year']} 年，{note}\n"
        "星级与潜力均为游戏设定。上海时间明日零点可再次免费投胎。"
    )
