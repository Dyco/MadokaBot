import base64
import json
import random
from datetime import datetime
from zoneinfo import ZoneInfo

from jinja2 import Template
from nonebot.adapters.onebot.v11 import MessageSegment
from nonebot_plugin_htmlrender import html_to_pic

from ..constants import ResType, SubFolder
from ..db.models import SignRecord, UserStats
from ..registry import get_skin_path
from ..utils import get_file
from .config import HTML_FILE_PATH

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


async def render_sign_card(
    user_name: str,
    user: UserStats,
    sign: SignRecord,
    reward_data: dict[str, int] | None = None,
) -> MessageSegment:
    """渲染签到或用户资料卡片。"""
    if not HTML_FILE_PATH.is_file():
        raise FileNotFoundError(f"签到模板不存在：{HTML_FILE_PATH}")

    font_file = get_file(ResType.FONT, SubFolder.SIGN, "font.ttf")
    if font_file is None:
        raise FileNotFoundError("签到字体资源不存在：font/sign/font.ttf")

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

    template = Template(HTML_FILE_PATH.read_text(encoding="utf-8"))
    html = template.render(
        title=title,
        items=items,
        quote=get_sign_quote(user.favorability),
        chara_b64=chara_b64,
        chara_name=chara_display_name,
        font_path=font_file.resolve().as_uri(),
        user_name=user_name,
        user_id=str(user.user_id),
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

    json_path = get_file(ResType.JSON, SubFolder.SIGN, "quotes.json")
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
