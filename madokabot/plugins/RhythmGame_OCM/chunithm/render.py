"""中二节奏 B30、新曲 B20 与 Selection 10 的成绩图片渲染。"""

import asyncio
from decimal import ROUND_DOWN, Decimal
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from nonebot.adapters.onebot.v11 import MessageSegment
from nonebot_plugin_htmlrender import html_to_pic

from madokabot.core.version import get_bot_version

from ..update_resources import local_image
from ..utils import display_time, image_uri
from .models import DIFFICULTIES, DIFFICULTY_KEYS, Best50, Player, Score
from .resources import FONT_ROOT, IMAGE_ROOT

TEMPLATE_DIR = Path(__file__).parent / "templates"
_environment = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR), encoding="utf-8"),
    autoescape=select_autoescape(("html", "xml")),
    undefined=StrictUndefined,
)
_render_limit = asyncio.Semaphore(2)


def score_labels(score: Score) -> tuple[str, str, str, str]:
    """转换评级、通关、连击与 FULL CHAIN 文本，区分金链和铂链。"""
    return (
        score.rank.upper().replace("P", "+"),
        score.clear.upper(),
        {"alljusticecritical": "AJC", "alljustice": "AJ", "fullcombo": "FC"}.get(
            score.full_combo, ""
        ),
        {"fullchain": "铂链", "fullchain2": "金链"}.get(score.full_chain, ""),
    )


def average_rating(scores: list[Score], size: int) -> str:
    """以固定席位数计算平均 Rating，缺位计零，截断至四位小数。"""
    total = sum((Decimal(str(score.rating)) for score in scores), Decimal(0))
    return format((total / size).quantize(Decimal("0.0000"), rounding=ROUND_DOWN), "f")


def score_card(score: Score, index: int, songs: dict[int, dict]) -> dict:
    """整理单谱分数、定数与状态，中二曲目 ID 保持原值。"""
    charts = songs.get(score.id, {}).get("difficulties", [])
    chart = next((item for item in charts if item["difficulty"] == score.level_index), {})
    rate, clear, combo, chain = score_labels(score)
    cover = local_image(IMAGE_ROOT, "jacket", score.id) or IMAGE_ROOT / "pic" / "cover.svg"
    return {
        "index": index, "id": score.id, "name": score.song_name,
        "difficulty": DIFFICULTY_KEYS[score.level_index],
        "difficulty_name": DIFFICULTIES[score.level_index],
        "level": score.level,
        "constant": f"{chart['level_value']:.1f}" if "level_value" in chart else "—",
        "score": f"{score.score:,}", "rating": f"{score.rating:.4f}",
        "rate": rate, "clear": clear, "combo": combo, "chain": chain,
        "cover": image_uri(cover),
    }


def render_b50_html(player: Player, bests: Best50, catalog: dict) -> str:
    """将 LXNS 原始分组整理为 B30、B20 和独立候选列表，不混入最近成绩。"""
    songs = {int(song["id"]): song for song in catalog.get("songs", [])}
    sections = []
    counted_scores = []
    for title, subtitle, scores, size, included in (
        ("BEST 30", "旧版本评分对象曲", bests.bests, 30, True),
        ("NEW 20", "现版本评分对象曲", bests.new_bests, 20, True),
        ("SELECTION 10", "候选评分对象曲 · 不计入 B50", bests.selections, 10, False),
    ):
        selected = sorted(scores, key=lambda score: (score.rating, score.score), reverse=True)[:size]
        if included:
            counted_scores.extend(selected)
        cards = [score_card(score, index, songs) for index, score in enumerate(selected, 1)]
        sections.append({
            "title": title, "subtitle": subtitle, "count": len(cards), "size": size,
            "average": average_rating(selected, size), "included": included,
            "cards": cards + [None] * (size - len(cards)),
        })
    icon = local_image(IMAGE_ROOT, "icon", player.map_icon.id) if player.map_icon else None
    character = local_image(IMAGE_ROOT, "character", player.character.id) if player.character else None
    plate = local_image(IMAGE_ROOT, "plate", player.name_plate.id) if player.name_plate else None
    trophy = (
        local_image(IMAGE_ROOT, "trophy", player.trophy.id)
        if player.trophy and player.trophy.color == "image" else None
    )
    return _environment.get_template("b50.html").render(
        player=player, sections=sections, average=average_rating(counted_scores, 50),
        upload_time=display_time(player.upload_time), bot_version=get_bot_version(),
        icon=image_uri(icon or IMAGE_ROOT / "pic" / "cover.svg"),
        character=image_uri(character), plate=image_uri(plate), trophy=image_uri(trophy),
        font=image_uri(FONT_ROOT / "font.ttf"), numbers_font=image_uri(FONT_ROOT / "numbers.otf"),
        background=image_uri(IMAGE_ROOT / "pic" / "background.svg"),
    )


async def render_b50(player: Player, bests: Best50, catalog: dict) -> MessageSegment:
    """通过项目公共浏览器将中二成绩页面渲染为 PNG 图片。"""
    html = await asyncio.to_thread(render_b50_html, player, bests, catalog)
    async with _render_limit:
        picture = await html_to_pic(
            html=html, template_path=TEMPLATE_DIR.resolve().as_uri(),
            viewport={"width": 1400, "height": 10}, full_page=True,
        )
    return MessageSegment.image(picture)
