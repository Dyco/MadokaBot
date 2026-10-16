"""每日投胎卡片与各模式地图渲染。"""

import asyncio
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from nonebot.adapters.onebot.v11 import MessageSegment
from nonebot_plugin_htmlrender import html_to_pic

from madokabot.core.resources import ResourceFolder, ResourceType, get_file
from madokabot.core.version import get_bot_version

from .attributes import attribute_rows
from .geography import focused_map, load_regional_map, load_world_map, result_location
from .modes import MODE_COMMANDS, MODE_NAMES
from .simulation import display_result

TEMPLATE_DIR = Path(__file__).parent / "templates"
_environment = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR), encoding="utf-8"),
    autoescape=select_autoescape(("html", "xml")),
    undefined=StrictUndefined,
)
_render_limit = asyncio.Semaphore(2)


def recent_history(result: dict) -> list[dict]:
    """整理最近历史并纠正朝韩误标，旧记录无法区分时如实显示两种可能。"""
    history = result.get("reborn_history") or [{
        "count": result.get("reborn_count", 1),
        "date": result["date"],
        "country": result["country"]["name"],
        "gender": result["gender"],
        "score": result["score"],
        "label": result["label"],
    }]
    rows = []
    for entry in reversed(history[-10:]):
        if entry["country"] == "朝韩非军事区":
            code = entry.get("country_code")
            if not code and entry["count"] == result.get("reborn_count"):
                code = result["country"]["code"]
            entry = entry | {"country": {"PRK": "朝鲜", "KOR": "韩国"}.get(code, "朝鲜／韩国")}
        rows.append(entry)
    return rows


def render_reborn_html(result: dict, name: str) -> str:
    """生成包含投胎次数、历史与项目版本的离线星级卡片，兼容旧记录。"""
    result = display_result(result)
    font = get_file(ResourceType.FONT, ResourceFolder.SIGN, "font.ttf")
    country = result["country"]
    mode = result.get("mode", "world")
    regional_map = load_regional_map(mode) if mode != "world" else {}
    regions = regional_map["regions"] if regional_map else load_world_map()
    region, marker_x, marker_y = result_location(result)
    view_box, map_scale, map_offsets = focused_map(region, marker_x, marker_y, mode=mode)
    rows = attribute_rows(result["attributes"])
    history = recent_history(result)
    return _environment.get_template("reborn.html").render(
        result=result,
        attribute_rows=rows,
        name=name,
        bot_version=get_bot_version(),
        reborn_count=result.get("reborn_count", 1),
        history_slots=history + [None] * (10 - len(history)),
        mode=mode,
        mode_name=MODE_NAMES[mode],
        title="每日投胎" if mode == "world" else MODE_COMMANDS[mode],
        regional_map=regional_map,
        regions=regions,
        marker_x=marker_x,
        marker_y=marker_y,
        map_view_box=view_box,
        map_scale=map_scale,
        map_offsets=map_offsets,
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


def result_text(result: dict, *, prefix: str, name: str = "") -> str:
    """图片不可用时返回次数、出生信息、星级评分及最近十次历史。"""
    result = display_result(result)
    country = result["country"]
    attributes = "\n".join(
        f"{row['name']}：{row['value_text']} 星（{row['title']}）"
        for row in attribute_rows(result["attributes"])
    )
    mode = result.get("mode", "world")
    title = "每日投胎" if mode == "world" else MODE_COMMANDS[mode]
    note = result.get("data_note", "中方案预测")
    history = recent_history(result)
    history_lines = [
        f"第{row['count']}次 {row['date'][5:]} {row['country']} · {row['gender']} · {row['score']}分 · {row['label'].split(' · ')[0]}"
        for row in history
    ]
    history_text = "\n".join(" ｜ ".join(history_lines[index:index + 5]) for index in range(0, len(history_lines), 5))
    introduction = f"{name}，" if name else ""
    return (
        f"{prefix}\n{title} · {result['date']}\n"
        f"{introduction}这是你的第{result.get('reborn_count', 1)}次投胎，这次你出生在\n"
        f"出生地：{country['name']}\n性别：{result['gender']}\n"
        f"抽中概率：{result['probability']:.4%}\n"
        f"{attributes}\n综合潜力：{result['score']}/100 · {result['label']}\n"
        f"人口数据：{result['source']} / {result['data_year']} 年，{note}\n"
        "星级与潜力均为游戏设定。上海时间明日零点可再次免费投胎。\n"
        f"最近十次投胎：\n{history_text}"
    )
