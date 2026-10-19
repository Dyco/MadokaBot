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
from .regions import result_region, world_region
from .simulation import display_result, load_population

TEMPLATE_DIR = Path(__file__).parent / "templates"
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
        "label": result["label"],
    }]
    rows = []
    for entry in reversed(history[-10:]):
        if entry["country"] == "朝韩非军事区":
            code = entry.get("country_code")
            if not code and entry["count"] == result.get("reborn_count"):
                code = result["country"]["code"]
            entry = entry | {"country": {"PRK": "朝鲜", "KOR": "韩国"}.get(code, "朝鲜／韩国")}
        if result.get("mode", "world") == "world":
            code = entry.get("country_code") or next(
                (row["code"] for row in load_population()["countries"] if row["name"] == entry["country"]), ""
            )
            area = result_region(result) if entry["count"] == result.get("reborn_count", 1) else (
                entry.get("world_region") or world_region(code)
            )
            if area:
                entry = entry | {"country": f"{entry['country']} - {area}"}
        rows.append(entry)
    return rows


def render_reborn_html(result: dict, name: str) -> str:
    """按模式生成离线卡片，作品身份使用配置字段，现实模式保留地图与星级。"""
    if result.get("mode") in {"anime", "games"}:
        return render_anime_html(result, name)
    if result.get("mode") == "isekai":
        return render_isekai_html(result, name)
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
        world_region=result_region(result),
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


def render_isekai_html(result: dict, name: str) -> str:
    """使用已保存的世界标题、父母身份与最近历史生成异世界卡片。"""
    font = get_file(ResourceType.FONT, ResourceFolder.SIGN, "font.ttf")
    history = list(reversed(result["reborn_history"][-10:]))
    return _environment.get_template("isekai.html").render(
        result=result,
        name=name,
        bot_version=get_bot_version(),
        font_uri=font.resolve().as_uri() if font else "",
        history_slots=history + [None] * (10 - len(history)),
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


def render_anime_html(result: dict, name: str) -> str:
    """使用保存的字段、评级与历史生成作品卡片，图片不展示资料说明与引用。"""
    font = get_file(ResourceType.FONT, ResourceFolder.SIGN, "font.ttf")
    history = list(reversed(result["reborn_history"][-10:]))
    return _environment.get_template("anime.html").render(
        result=result, name=name, mode_name=MODE_NAMES[result["mode"]],
        font_uri=font.resolve().as_uri() if font else "",
        history_slots=history + [None] * (10 - len(history)),
    )


def result_text(result: dict, *, prefix: str, name: str = "") -> str:
    """图片不可用时按模式返回完整档案及最近十次历史。"""
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
    note = result.get("data_note", "中方案预测")
    area = result_region(result)
    destination = country["name"] + (f" - {area}" if area else "")
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
        f"出生地：{destination}\n性别：{result['gender']}\n"
        f"抽中概率：{result['probability']:.4%}\n"
        f"{attributes}\n综合潜力：{result['score']}/100 · {result['label']}\n"
        f"人口数据：{result['source']} / {result['data_year']} 年，{note}\n"
        "星级与潜力均为游戏设定。上海时间明日零点可再次免费投胎。\n"
        f"最近十次投胎：\n{history_text}"
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
    """按作品分区输出身份、投胎评级、资料或玩法说明及历史摘要。"""
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
