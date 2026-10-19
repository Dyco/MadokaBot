"""每日投胎卡片与各模式地图渲染。"""

import asyncio
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from nonebot.adapters.onebot.v11 import MessageSegment
from nonebot_plugin_htmlrender import html_to_pic

from madokabot.core.resources import ResourceFolder, ResourceType, assets, get_file
from madokabot.core.version import get_bot_version

from .anime import ANIME_VERSION
from .anime_life import CATEGORY_NAMES, anime_life_rows
from .attributes import attribute_rows
from .geography import focused_map, load_regional_map, load_world_map, result_location
from .life import life_rows
from .modes import MODE_COMMANDS, MODE_NAMES
from .potential import score_tier
from .regions import result_region, world_region
from .simulation import display_result, load_population
from .text import anime_text

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
    """整理最近历史、纠正朝韩误标，并为世界记录补充可确定的地理分区。"""
    history = result.get("reborn_history") or [{
        "count": result.get("reborn_count", 1),
        "date": result["date"],
        "country": result["country"]["name"],
        "gender": result["gender"],
        "score": result["score"],
    }]
    rows = []
    for entry in reversed(history[-10:]):
        if entry["country"] == "朝韩非军事区":
            code = entry.get("country_code")
            if not code and entry["count"] == result.get("reborn_count"):
                code = result["country"]["code"]
            entry = entry | {"country": {"PRK": "朝鲜", "KOR": "韩国"}.get(code, "朝鲜／韩国")}
        if entry["count"] == result.get("reborn_count", 1):
            entry = entry | {"score": result["score"]}
        if result.get("mode", "world") == "world":
            code = entry.get("country_code") or next(
                (row["code"] for row in load_population()["countries"] if row["name"] == entry["country"]), ""
            )
            area = result_region(result) if entry["count"] == result.get("reborn_count", 1) else (
                entry.get("world_region") or world_region(code)
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
    result = display_result(result)
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
    """将已保存的出生、父母与先天条件分栏生成异世界横版卡片。"""
    font = get_file(ResourceType.FONT, ResourceFolder.SIGN, "font.ttf")
    history = list(reversed(result["reborn_history"][-10:]))
    return _environment.get_template("isekai.html").render(
        result=result,
        card_size=CARD_VIEWPORT,
        name=name,
        bot_version=get_bot_version(),
        font_uri=font.resolve().as_uri() if font else "",
        history_slots=history + [None] * (10 - len(history)),
    )


async def render_reborn_card(result: dict, name: str) -> MessageSegment:
    """按固定二比一视口生成 PNG，保留渲染器默认双倍像素。"""
    async with _render_limit:
        picture = await html_to_pic(
            html=render_reborn_html(result, name),
            template_path=TEMPLATE_DIR.resolve().as_uri(),
            viewport=CARD_VIEWPORT,
            full_page=False,
        )
    return MessageSegment.image(picture)


def render_anime_html(result: dict, name: str) -> str:
    """新版动漫按题材呈现标题图与人生结局，二游及已保存的旧动漫使用原作品卡。"""
    font = get_file(ResourceType.FONT, ResourceFolder.SIGN, "font.ttf")
    history = list(reversed(result["reborn_history"][-10:]))
    if result.get("result_version") == ANIME_VERSION:
        history = [entry | {
            "score_text": f"{entry['score']}分" if "score" in entry else entry["rating"],
            "score_tier": score_tier(entry["score"]) if "score" in entry else "slate",
        } for entry in history]
        image = assets.get_dir(ResourceType.IMAGE) / "reborn" / result["world"]["logo"]
        return _environment.get_template("anime_card.html").render(
            result=result, name=name, card_size=CARD_VIEWPORT,
            category_name=CATEGORY_NAMES[result["world"]["category"]],
            attribute_rows=attribute_rows(result["attributes"]), life_rows=anime_life_rows(result),
            score_tier=score_tier(result["score"]), bot_version=get_bot_version(),
            font_uri=font.resolve().as_uri() if font else "", title_image_uri=image.resolve().as_uri(),
            history_slots=history + [None] * (10 - len(history)),
        )
    return _environment.get_template("anime.html").render(
        result=result, name=name, mode_name=MODE_NAMES[result["mode"]],
        card_size=CARD_VIEWPORT,
        bot_version=get_bot_version(),
        font_uri=font.resolve().as_uri() if font else "",
        history_slots=history + [None] * (10 - len(history)),
    )


def result_text(result: dict, *, prefix: str, name: str = "") -> str:
    """图片不可用时按模式返回档案，现实模式展示星级、评分、人生结果及记录。"""
    if result.get("mode") in {"anime", "games"}:
        return anime_result_text(result, prefix=prefix, name=name)
    if result.get("mode") == "isekai":
        return isekai_result_text(result, prefix=prefix, name=name)
    result = display_result(result)
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
    """按已保存快照展示时代、父母力量与出生条件，同时支持既有档案。"""
    child = result["child"]
    household = result["household"]
    lineage = f" · {child['lineage']}" if child["lineage"] else ""
    parent_lines = []
    for parent in result["parents"]:
        powers = "；".join(power["name"] for power in parent.get("powers", [parent["power"]]))
        parent_lines.append(
            f"{parent['role']}：{parent['species']}"
            f"{(' · ' + parent['lineage']) if parent['lineage'] else ''} · {parent['occupation']}\n"
            f"身份：{parent['identity']} ｜ 实力：{powers}"
        )
        if parent.get("affiliation"):
            parent_lines.append(f"关系：{parent['affiliation']}")
        parent_lines.extend(parent.get("notes", []))
    parents = "\n".join(parent_lines)
    setting = f"背景：{result['setting']['name']}\n{result['setting']['description']}\n" if "setting" in result else ""
    birthplace_context = f"{result['birthplace']['context']}\n" if "context" in result["birthplace"] else ""
    details = []
    if child.get("features"):
        details.append("物种背景：" + "、".join(child["features"]))
    if child.get("life_span"):
        details.append(child["life_span"])
    details.extend(f"{row['label']}：{row['name']}\n{row['description']}" for row in child.get("aspects", []))
    details.extend(child.get("notes", []))
    birth_details = "\n".join(details) + "\n" if details else ""
    history = "\n".join(
        f"第{row['count']}次 {row['date'][5:]} {row['world']} · {row['species']} · {row['gender']} · {row['family']}"
        for row in reversed(result["reborn_history"][-10:])
    )
    return (
        f"{prefix}\n{result['title']} · {result['date']}\n"
        f"{name}，这是你的第{result['reborn_count']}次异世界投胎\n"
        f"世界：{result['world']['title']}\n{result['world']['description']}\n{setting}"
        f"出生地：{result['birthplace']['name']}\n{result['birthplace']['description']}\n"
        f"{birthplace_context}"
        f"种族：{child['species']}{lineage} ｜ 性别：{result['gender']}\n"
        f"出生状态：{child['birth_state']}\n"
        f"家庭：{household['name']}（{household['rarity']}）\n{household['description']}\n"
        f"{parents}\n家庭资源：{'、'.join(household['resources'])}\n"
        f"{child.get('trait_label', '先天特征')}：{child['trait']['name']}\n{child['trait']['description']}\n{birth_details}"
        f"成长方向：{'、'.join(household['directions'])}\n"
        f"成长课题：{household['challenge']}\n{result['notice']}\n"
        f"最近十次异世界投胎：\n{history}"
    )


def anime_result_text(result: dict, *, prefix: str, name: str) -> str:
    """新版动漫输出题材人生，二游及旧动漫保留已存的分区字段与引用。"""
    if result.get("result_version") == ANIME_VERSION:
        history = "\n".join(
            f"第{row['count']}次 {row['world']} · "
            f"{str(row['score']) + '分' if 'score' in row else row['rating']} "
            f"{'♂' if row['gender'] == '男' else '♀'}"
            for row in reversed(result["reborn_history"][-10:])
        )
        return (
            f"{prefix}\n{result['title']} · {result['date']}\n"
            f"{name + '，' if name else ''}这是你的第{result['reborn_count']}次二次元投胎\n"
            f"{anime_text(result)}\n{result['notice']}\n记录：\n{history}"
        )
    numbers = {source["id"]: index for index, source in enumerate(result["sources"], 1)}
    sections = []
    for section in result["sections"]:
        lines = []
        for row in section["rows"]:
            refs = "".join(f"[{numbers[ref]}]" for ref in row["source_refs"])
            description = f"\n  {row['description']}" if row["description"] else ""
            lines.append(f"{row['label']}：{row['value']}{refs}{description}")
        sections.append(f"——{section['title']}——\n" + "\n".join(lines))
    fields = "\n\n".join(sections)
    rating = result["rating"]
    rating_refs = "".join(f"[{numbers[ref]}]" for ref in rating["source_refs"])
    sources = "\n".join(
        f"[{index}] {source['title']}（{source['checked_at']}）\n{source['url']}"
        for index, source in enumerate(result["sources"], 1)
    )
    history = "\n".join(
        f"第{row['count']}次 {row['date'][5:]} {row['world']} · {row['gender']} · {row['rating']} · {row['summary']}"
        for row in reversed(result["reborn_history"][-10:])
    )
    introduction = f"{name}，" if name else ""
    mode_name = MODE_NAMES[result["mode"]]
    return (
        f"{prefix}\n{result['title']} · {result['date']}\n"
        f"{introduction}这是你的第{result['reborn_count']}次{mode_name}投胎\n"
        f"世界：{result['world']['title']} ｜ 性别：{result['gender']}\n"
        f"{result['world']['description']}\n资料范围：{result['world']['scope']}\n\n{fields}\n\n"
        f"{rating['label']}：{rating['value']}{rating_refs}\n{rating['description']}\n"
        f"{result['notice']}\n资料版本：{result['dataset_version']}\n"
        f"资料来源：\n{sources}\n最近十次{mode_name}投胎：\n{history}"
    )
