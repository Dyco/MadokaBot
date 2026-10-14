"""舞萌 B50 图片的数据整理与离线模板渲染。"""

import asyncio
import math
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from nonebot.adapters.onebot.v11 import MessageSegment
from nonebot_plugin_htmlrender import html_to_pic

from madokabot.core.version import get_bot_version

from .models import DIFFICULTIES, DIFFICULTY_KEYS, Best50, Player, Score
from .resources import FONT_ROOT, IMAGE_ROOT
from .update_resources import local_image
from .utils import display_time, image_uri

TEMPLATE_DIR = Path(__file__).parent / "templates"
_environment = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR), encoding="utf-8"),
    autoescape=select_autoescape(("html", "xml")),
    undefined=StrictUndefined,
)
_render_limit = asyncio.Semaphore(2)


def score_labels(score: Score) -> tuple[str, str, str]:
    """将评级、连击与同步状态转换为游戏内显示文本。"""
    return (
        score.rate.upper().replace("P", "+"),
        {"fcp": "FC+", "app": "AP+"}.get(score.fc, (score.fc or "").upper()),
        {"fsd": "FDX", "fsdp": "FDX+", "fsp": "FS+", "sync": "SYNC"}.get(
            score.fs, (score.fs or "").upper()
        ),
    )


def score_card(score: Score, index: int, songs: dict[int, dict]) -> dict:
    """整理单张成绩卡的定数、曲绘与状态，Rating 向下取整。"""
    difficulty = DIFFICULTY_KEYS[score.level_index]
    song = songs.get(score.id, {})
    charts = song.get("difficulties", {}).get(score.type, [])
    chart = next((item for item in charts if item["difficulty"] == score.level_index), {})
    rate, fc, fs = score_labels(score)
    fs_key = {"fsd": "fdx", "fsdp": "fdxp"}.get(score.fs, score.fs)
    cover = local_image(IMAGE_ROOT, "jacket", score.id) or IMAGE_ROOT / "cover" / "0.png"
    return {
        "index": index,
        "id": score.id,
        "name": score.song_name,
        "level": score.level,
        "constant": f"{chart['level_value']:.1f}" if "level_value" in chart else "—",
        "difficulty": difficulty,
        "difficulty_name": DIFFICULTIES[score.level_index],
        "type": "DX" if score.type == "dx" else "SD",
        "achievements": f"{score.achievements:.4f}",
        "rating": math.floor(score.dx_rating),
        "dx_score": score.dx_score,
        "dx_star": score.dx_star,
        "rate": rate,
        "fc": fc,
        "fs": fs,
        "cover": image_uri(cover),
        "card_bg": image_uri(IMAGE_ROOT / "pic" / f"b50_score_{difficulty}.png"),
        "fc_icon": image_uri(IMAGE_ROOT / "pic" / f"status_{score.fc}.png") if fc else "",
        "fs_icon": image_uri(IMAGE_ROOT / "pic" / f"status_{fs_key}.png") if fs else "",
    }


def render_b50_html(player: Player, bests: Best50, catalog: dict) -> str:
    """生成本地资源驱动的 B50 页面，缺少成绩时保留空位。"""
    songs = {int(song["id"]): song for song in catalog.get("songs", [])}
    sections = []
    for title, subtitle, scores, size, total in (
        ("B35", "旧版本谱面", bests.standard, 35, bests.standard_total),
        ("B15", "现版本谱面", bests.dx, 15, bests.dx_total),
    ):
        cards = [
            score_card(score, index, songs)
            for index, score in enumerate(sorted(scores, key=lambda s: s.dx_rating, reverse=True)[:size], 1)
        ]
        sections.append({
            "title": title, "subtitle": subtitle, "count": len(cards),
            "size": size, "total": total, "cards": cards + [None] * (size - len(cards)),
        })
    icon = local_image(IMAGE_ROOT, "icon", player.icon.id) if player.icon else None
    plate = local_image(IMAGE_ROOT, "plate", player.name_plate.id) if player.name_plate else None
    return _environment.get_template("b50.html").render(
        player=player,
        sections=sections,
        total=bests.standard_total + bests.dx_total,
        upload_time=display_time(player.upload_time),
        bot_version=get_bot_version(),
        background=image_uri(IMAGE_ROOT / "pic" / "circle" / "b50.png"),
        logo=image_uri(IMAGE_ROOT / "pic" / "circle" / "logo.png"),
        course_rank=image_uri(IMAGE_ROOT / "pic" / f"UI_DNM_DaniPlate_{player.course_rank:02d}.png"),
        class_rank=image_uri(IMAGE_ROOT / "pic" / f"UI_FBR_Class_{player.class_rank:02d}.png"),
        icon=image_uri(icon or IMAGE_ROOT / "pic" / "UI_Icon_509506.png"),
        plate=image_uri(plate),
        font=image_uri(FONT_ROOT / "font" / "ResourceHanRoundedCN-Bold.ttf"),
    )


async def render_b50(player: Player, bests: Best50, catalog: dict) -> MessageSegment:
    """使用项目公共浏览器渲染能力生成完整 B50 PNG。"""
    html = await asyncio.to_thread(render_b50_html, player, bests, catalog)
    async with _render_limit:
        picture = await html_to_pic(
            html=html,
            template_path=TEMPLATE_DIR.resolve().as_uri(),
            viewport={"width": 1400, "height": 10},
            full_page=True,
        )
    return MessageSegment.image(picture)
