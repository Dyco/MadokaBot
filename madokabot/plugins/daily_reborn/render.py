"""每日投胎卡片与各模式地图渲染。"""

import asyncio
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from nonebot.adapters.onebot.v11 import MessageSegment
from nonebot_plugin_htmlrender import html_to_pic

from madokabot.core.resources import ResourceFolder, ResourceType, assets, get_file
from madokabot.core.version import get_bot_version

from .anime_life import CATEGORY_NAMES, anime_life_rows
from .attributes import attribute_rows
from .games import game_detail_rows
from .geography import focused_map, load_regional_map, load_world_map, result_location
from .life import life_rows
from .modes import MODE_COMMANDS, MODE_NAMES
from .potential import score_tier
from .regions import result_region, world_region
from .text import OLD_RESULT_NOTICE, anime_text, games_text, is_current_result, isekai_text, recent_records

TEMPLATE_DIR = Path(__file__).parent / "templates"
# 所有模式统一使用九百乘四百五十视口，像素倍率沿用渲染器默认值。
CARD_VIEWPORT = {"width": 900, "height": 450}
_environment = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR), encoding="utf-8"),
    autoescape=select_autoescape(("html", "xml")),
    undefined=StrictUndefined,
)
_render_limit = asyncio.Semaphore(2)


def recent_history(result: dict) -> list[dict]:
    """整理有效的现实投胎历史，世界记录显示已保存的地理分区。"""
    rows = []
    for entry in recent_records(result, "count", "date", "country", "country_code", "gender", "score"):
        if result["mode"] == "world":
            area = result_region(result) if entry["count"] == result["reborn_count"] else (
                entry.get("world_region") or world_region(entry["country_code"])
            )
            if area:
                entry = entry | {"country": f"{entry['country']} - {area}"}
        rows.append(entry | {"score_tier": score_tier(entry["score"])})
    return rows


def render_reborn_html(result: dict, name: str) -> str:
    """按模式生成固定比例横版卡片，现实模式将地图与属性分栏展示。"""
    if result.get("mode") in {"anime", "games"}:
        return render_anime_html(result, name)
    if result.get("mode") == "isekai":
        return render_isekai_html(result, name)
    font = get_file(ResourceType.FONT, ResourceFolder.SIGN, "font.ttf")
    mode = result.get("mode", "world")
    regional_map = load_regional_map(mode) if mode != "world" else {}
    regions = regional_map["regions"] if regional_map else load_world_map()
    region, marker_x, marker_y = result_location(result)
    view_box, map_scale, map_offsets = focused_map(region, marker_x, marker_y, mode=mode)
    rows = attribute_rows(result["attributes"])
    history = recent_history(result)
    return _environment.get_template("reborn.html").render(
        result=result,
        card_size=CARD_VIEWPORT,
        world_region=result_region(result),
        attribute_rows=rows,
        life_rows=life_rows(result["life"]),
        score_tier=score_tier(result["score"]),
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
    )


def render_isekai_html(result: dict, name: str) -> str:
    """渲染新版综合人生卡片，历史缺少必要字段时直接跳过。"""
    font = get_file(ResourceType.FONT, ResourceFolder.SIGN, "font.ttf")
    history = recent_records(result, "count", "world", "gender", "score")
    history = [entry | {"score_tier": score_tier(entry["score"])} for entry in history]
    return _environment.get_template("isekai.html").render(
        result=result,
        attribute_rows=attribute_rows(result["attributes"]),
        life_rows=result["life"],
        score_tier=score_tier(result["score"]),
        card_size=CARD_VIEWPORT,
        name=name,
        bot_version=get_bot_version(),
        font_uri=font.resolve().as_uri() if font else "",
        history_slots=history + [None] * (10 - len(history)),
    )


async def render_reborn_card(result: dict, name: str) -> MessageSegment:
    """按固定二比一视口生成 PNG，保留渲染器默认双倍像素。"""
    if not is_current_result(result):
        return MessageSegment.text(OLD_RESULT_NOTICE)
    async with _render_limit:
        picture = await html_to_pic(
            html=render_reborn_html(result, name),
            template_path=TEMPLATE_DIR.resolve().as_uri(),
            viewport=CARD_VIEWPORT,
            full_page=False,
        )
    return MessageSegment.image(picture)


def render_anime_html(result: dict, name: str) -> str:
    """按当前模式渲染二次元和二游标题图卡片，跳过字段不完整的历史。"""
    font = get_file(ResourceType.FONT, ResourceFolder.SIGN, "font.ttf")
    image = assets.get_dir(ResourceType.IMAGE) / "reborn" / result["world"]["logo"]
    context = {
        "result": result, "name": name, "card_size": CARD_VIEWPORT,
        "attribute_rows": attribute_rows(result["attributes"]), "bot_version": get_bot_version(),
        "font_uri": font.resolve().as_uri() if font else "", "title_image_uri": image.resolve().as_uri(),
    }
    if result["mode"] == "games":
        history = [entry | {
            "score_text": entry["rating"], "score_tier": entry["rating_tier"],
        } for entry in recent_records(result, "count", "world", "gender", "rating", "rating_tier")]
        return _environment.get_template("games_card.html").render(
            **context, detail_rows=game_detail_rows(result), score_tier=result["rating"]["tier"],
            history_slots=history + [None] * (10 - len(history)),
        )
    history = [entry | {
        "score_text": f"{entry['score']}分", "score_tier": score_tier(entry["score"]),
    } for entry in recent_records(result, "count", "world", "gender", "score")]
    return _environment.get_template("anime_card.html").render(
        **context, category_name=CATEGORY_NAMES[result["world"]["category"]],
        life_rows=anime_life_rows(result), score_tier=score_tier(result["score"]),
        history_slots=history + [None] * (10 - len(history)),
    )


def result_text(result: dict, *, prefix: str, name: str = "") -> str:
    """图片不可用时按模式返回档案，现实模式展示星级、评分、人生结果及记录。"""
    if not is_current_result(result):
        return f"{prefix}\n{OLD_RESULT_NOTICE}"
    if result.get("mode") in {"anime", "games"}:
        return anime_result_text(result, prefix=prefix, name=name)
    if result.get("mode") == "isekai":
        return isekai_result_text(result, prefix=prefix, name=name)
    country = result["country"]
    attributes = "\n".join(
        f"{row['name']}：{row['value_text']} 星（{row['title']}）"
        for row in attribute_rows(result["attributes"])
    )
    mode = result.get("mode", "world")
    title = "每日投胎" if mode == "world" else MODE_COMMANDS[mode]
    area = result_region(result)
    destination = country["name"] + (f" - {area}" if area else "")
    history = recent_history(result)
    history_lines = [
        f"第{row['count']}次 {row['date'][5:]} {row['country']} · {row['gender']} · {row['score']}分"
        for row in history
    ]
    history_text = "\n".join(" ｜ ".join(history_lines[index:index + 5]) for index in range(0, len(history_lines), 5))
    introduction = f"{name}，" if name else ""
    life_text = "\n".join(f"{row['label']}：{row['value']}" for row in life_rows(result["life"]))
    return (
        f"{prefix}\n{title} · {result['date']}\n"
        f"{introduction}这是你的第{result.get('reborn_count', 1)}次投胎，这次你出生在\n"
        f"出生地：{destination}\n性别：{result['gender']}\n"
        f"抽中概率：{result['probability']:.4%}\n"
        f"{attributes}\n综合评分：{result['score']}/100\n{life_text}\n"
        "属性与人生结果均为游戏设定。上海时间明日零点可再次免费投胎。\n"
        f"记录：\n{history_text}"
    )


def isekai_result_text(result: dict, *, prefix: str, name: str) -> str:
    """回复综合人生与有效历史，不补全旧档案。"""
    history = "\n".join(
        f"第{row['count']}次 {row['world']} - {row['score']}分"
        for row in recent_records(result, "count", "world", "gender", "score")
    )
    return f"{prefix}\n{name}，这是你的第{result['reborn_count']}次异世界投胎\n{isekai_text(result)}\n记录：\n{history}"


def anime_result_text(result: dict, *, prefix: str, name: str) -> str:
    """输出当前二次元或二游档案及完整历史条目。"""
    if result["mode"] == "games":
        history = "\n".join(
            f"第{row['count']}次 {row['world']} · {row['rating']} "
            f"{'♂' if row['gender'] == '男' else '♀'}"
            for row in recent_records(result, "count", "world", "gender", "rating", "rating_tier")
        )
        mode_name, content = "二游", games_text(result)
    else:
        history = "\n".join(
            f"第{row['count']}次 {row['world']} · {row['score']}分 "
            f"{'♂' if row['gender'] == '男' else '♀'}"
            for row in recent_records(result, "count", "world", "gender", "score")
        )
        mode_name, content = "二次元", anime_text(result)
    return (
        f"{prefix}\n{result['title']} · {result['date']}\n"
        f"{name + '，' if name else ''}这是你的第{result['reborn_count']}次{mode_name}投胎\n"
        f"{content}\n{result['notice']}\n记录：\n{history}"
    )
