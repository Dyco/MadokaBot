"""舞萌 B50 图片的数据整理与离线模板渲染。"""

import asyncio
import math
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from nonebot.adapters.onebot.v11 import MessageSegment
from nonebot_plugin_htmlrender import html_to_pic

from madokabot.core.version import get_bot_version

from .config import config
from .models import DIFFICULTIES, DIFFICULTY_KEYS, Best50, Player, Score
from .resources import FONT_ROOT, IMAGE_ROOT
from .update_resources import local_image
from .utils import image_uri

TEMPLATE_DIR = Path(__file__).parent / "templates"
_environment = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR), encoding="utf-8"),
    autoescape=select_autoescape(("html", "xml")),
    undefined=StrictUndefined,
)
_render_limit = asyncio.Semaphore(2)


def rating_background(rating: int, theme_root: Path) -> Path:
    """按 Rating 分段选择主题底板，缺失编号时向下查找最高可用素材。"""
    index = rating // 2000 + 1 if rating < 10000 else rating // 1000 - 4
    for number in range(index, 0, -1):
        path = theme_root / f"UI_CMN_DXRating_{number:02d}.png"
        if path.is_file():
            return path
    raise FileNotFoundError(f"舞萌主题缺少 DX Rating 底板：{theme_root}")


def score_labels(score: Score) -> tuple[str, str, str]:
    """将评级、连击与同步状态转换为游戏内显示文本。"""
    return (
        score.rate.upper().replace("P", "+"),
        {"fcp": "FC+", "app": "AP+"}.get(score.fc, (score.fc or "").upper()),
        {"fsd": "FDX", "fsdp": "FDX+", "fsp": "FS+", "sync": "SYNC"}.get(
            score.fs, (score.fs or "").upper()
        ),
    )


def score_card(score: Score, index: int, songs: dict[int, dict], theme_root: Path) -> dict:
    """按谱面难度选择完整卡片底板，并整理成绩、评级与圆形状态图标。"""
    difficulty = DIFFICULTY_KEYS[score.level_index]
    song = songs.get(score.id, {})
    charts = song.get("difficulties", {}).get(score.type, [])
    chart = next((item for item in charts if item["difficulty"] == score.level_index), {})
    rate, fc, fs = score_labels(score)
    fs_key = {"fs": "FS", "fsp": "FSp", "fsd": "FSD", "fsdp": "FSDp", "sync": "Sync"}.get(score.fs)
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
        "rank_icon": image_uri(theme_root / f"UI_TTR_Rank_{rate.replace('+', 'p')}.png"),
        "type_icon": image_uri(IMAGE_ROOT / "pic" / f"{'DX' if score.type == 'dx' else 'SD'}.png"),
        "fc_icon": image_uri(IMAGE_ROOT / "pic" / f"UI_CHR_PlayBonus_{fc.replace('+', 'p')}.png") if fc else "",
        "fs_icon": image_uri(IMAGE_ROOT / "pic" / f"UI_CHR_PlayBonus_{fs_key}.png") if fs_key else "",
    }


def render_b50_html(player: Player, bests: Best50, catalog: dict) -> str:
    """按配置加载主题素材，以旧曲 B35、新曲 B15 标题组织成绩卡片。"""
    theme_root = IMAGE_ROOT / "pic" / config.rhythmgame_maimai_theme
    background = theme_root / "b50.png"
    if not background.is_file():
        raise FileNotFoundError(f"舞萌 B50 主题底图不存在：{background}")
    songs = {int(song["id"]): song for song in catalog.get("songs", [])}
    sections = []
    for title, scores, size in (
        ("旧曲 B35", bests.standard, 35),
        ("新曲 B15", bests.dx, 15),
    ):
        cards = [
            score_card(score, index, songs, theme_root)
            for index, score in enumerate(sorted(scores, key=lambda s: s.dx_rating, reverse=True)[:size], 1)
        ]
        sections.append({
            "title": title, "cards": cards + [None] * (size - len(cards)),
        })
    icon = local_image(IMAGE_ROOT, "icon", player.icon.id) if player.icon else None
    plate = local_image(IMAGE_ROOT, "plate", player.name_plate.id) if player.name_plate else None
    trophy_color = (player.trophy.color or "normal").capitalize() if player.trophy else "Normal"
    return _environment.get_template("b50.html").render(
        player=player,
        sections=sections,
        bot_version=get_bot_version(),
        background=image_uri(background),
        logo=image_uri(theme_root / "logo.png"),
        course_rank=image_uri(IMAGE_ROOT / "pic" / f"UI_DNM_DaniPlate_{player.course_rank:02d}.png"),
        class_rank=image_uri(IMAGE_ROOT / "pic" / f"UI_FBR_Class_{player.class_rank:02d}.png"),
        icon=image_uri(icon or IMAGE_ROOT / "pic" / "UI_Icon_509506.png"),
        plate=image_uri(plate or IMAGE_ROOT / "pic" / "UI_Plate_550101.png"),
        name_frame=image_uri(IMAGE_ROOT / "pic" / "Name.png"),
        trophy_frame=image_uri(IMAGE_ROOT / "shougou" / f"UI_CMN_Shougou_{trophy_color}.png"),
        rating_background=image_uri(rating_background(player.rating, theme_root)),
        rating_digits=[
            image_uri(IMAGE_ROOT / "pic" / f"UI_NUM_Drating_{digit}.png") if digit != " " else ""
            for digit in f"{player.rating:5d}"
        ],
        font=image_uri(FONT_ROOT / "font" / "ResourceHanRoundedCN-Bold.ttf"),
        numbers_font=image_uri(FONT_ROOT / "font" / "Torus SemiBold.otf"),
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
