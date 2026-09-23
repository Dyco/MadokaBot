import base64
import json
import random
from datetime import datetime
from zoneinfo import ZoneInfo

from jinja2 import Template
from nonebot.adapters.onebot.v11 import MessageSegment
from nonebot_plugin_datastore import create_session
from nonebot_plugin_htmlrender import html_to_pic

from madokabot.core.resources import ResourceType, ResourceFolder, get_file
from madokabot.core.user.models import SignRecord, UserStats
from madokabot.core.user.queries import UserQueries
from madokabot.default.shop.catalog import get_skin_path
from .config import HTML_FILE_PATH

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def format_rank_points(points: int) -> str:
    """缩写榜单积分，带单位时保留一位小数，超出 B 后使用科学计数法。"""
    for divisor, unit in (
        (1, ""),
        (1_000, "K"),
        (1_000_000, "M"),
        (1_000_000_000, "B"),
    ):
        value = points / divisor
        if abs(round(value, 1)) < 1_000:
            return f"{value:.1f}{unit}" if unit else str(points)
    return f"{points:.1e}"


def mask_user_id(user_id: str) -> str:
    """QQ 号仅展示前后两位，中间统一替换为两个星号。"""
    return f"{user_id[:2]}**{user_id[-2:]}"


async def render_sign_card(
    user_name: str,
    user: UserStats,
    sign: SignRecord,
    reward_data: dict[str, int] | None = None,
) -> MessageSegment:
    """渲染签到或用户资料卡片。"""
    if not HTML_FILE_PATH.is_file():
        raise FileNotFoundError(f"签到模板不存在：{HTML_FILE_PATH}")

    font_file = get_file(ResourceType.FONT, ResourceFolder.SIGN, "font.ttf")
    if font_file is None:
        raise FileNotFoundError("签到字体资源不存在：font/sign/font.ttf")

    number_font_file = get_file(
        ResourceType.FONT, ResourceFolder.SIGN, "RobotoFlex.ttf"
    )
    if number_font_file is None:
        raise FileNotFoundError("签到字体资源不存在：font/sign/RobotoFlex.ttf")

    english_font_file = get_file(
        ResourceType.FONT, ResourceFolder.SIGN, "PlusJakartaSans.ttf"
    )
    if english_font_file is None:
        raise FileNotFoundError("签到字体资源不存在：font/sign/PlusJakartaSans.ttf")

    chara_path = get_skin_path(user.skin_asset)
    chara_display_name = None
    chara_b64 = None
    if chara_path is not None:
        chara_display_name = chara_path.stem
        image_data = base64.b64encode(chara_path.read_bytes()).decode()
        chara_b64 = f"data:image/png;base64,{image_data}"

    if reward_data is not None:
        title = "每日签到"
        points_gain = reward_data["reward_points"] + reward_data["bonus_point"]
        favor_gain = reward_data["reward_favor"]
        continuous_delta = "+1" if sign.continuous_days > 1 else "初次"
        items = [
            ("总积分", f"{user.points:,}", f"+{points_gain}"),
            ("好感度", f"{user.favorability} 点", f"+{favor_gain}"),
            ("连续陪伴", f"{sign.continuous_days} 天", continuous_delta),
            ("累计签到", f"{sign.total_count} 次", None),
        ]
    else:
        title = "用户资料"
        items = [
            ("总积分", f"{user.points:,}", None),
            ("好感度", f"{user.favorability} 点", None),
            ("连续陪伴", f"{sign.continuous_days} 天", None),
            ("累计签到", f"{sign.total_count} 次", None),
        ]

    async with create_session() as session:
        points_ranking = await UserQueries.get_points_ranking(session)
    ranking = [
        (
            nickname or "未命名",
            mask_user_id(uid),
            format_rank_points(points),
            total_count,
        )
        for uid, nickname, points, total_count in points_ranking
    ]
    template = Template(HTML_FILE_PATH.read_text(encoding="utf-8"), autoescape=True)
    html = template.render(
        title=title,
        items=items,
        quote=get_sign_quote(user.favorability),
        chara_b64=chara_b64,
        chara_name=chara_display_name,
        font_path=font_file.resolve().as_uri(),
        number_font_path=number_font_file.resolve().as_uri(),
        english_font_path=english_font_file.resolve().as_uri(),
        user_name=user.display_name or user_name,
        user_id=mask_user_id(str(user.user_id)),
        ranking=ranking,
        current_time=datetime.now(_SHANGHAI_TZ).strftime("%Y-%m-%d %H:%M:%S"),
    )

    image_bytes = await html_to_pic(
        html=html,
        viewport={"width": 900, "height": 600},
    )
    return MessageSegment.image(image_bytes)


def get_sign_quote(favorability: int) -> str:
    """根据当前时间与好感度选择一句台词。"""
    hour = datetime.now(_SHANGHAI_TZ).hour
    if 5 <= hour < 7:
        time_tag = "early morning"
    elif 7 <= hour < 11:
        time_tag = "morning"
    elif 11 <= hour < 13:
        time_tag = "noon"
    elif 13 <= hour < 17:
        time_tag = "afternoon"
    elif 17 <= hour < 19:
        time_tag = "dusk"
    elif 19 <= hour < 24:
        time_tag = "night"
    else:
        time_tag = "late night"

    if favorability < 30:
        favor_tag = "low"
    elif favorability < 60:
        favor_tag = "medium"
    else:
        favor_tag = "high"

    json_path = get_file(ResourceType.JSON, ResourceFolder.SIGN, "quotes.json")
    if json_path is None:
        raise FileNotFoundError("签到台词资源不存在：json/sign/quotes.json")

    all_quotes = json.loads(json_path.read_text(encoding="utf-8"))
    matching_quotes = [
        quote["台词"]
        for quote in all_quotes
        if quote["时间"] == time_tag and quote["好感"] == favor_tag
    ]
    if not matching_quotes:
        return "……没什么好说的。"
    return random.choice(matching_quotes)
