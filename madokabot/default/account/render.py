import base64
import json
import random
from datetime import datetime
from zoneinfo import ZoneInfo

from jinja2 import Template
from nonebot.adapters.onebot.v11 import MessageSegment
from nonebot_plugin_datastore import create_session
from nonebot_plugin_htmlrender import html_to_pic

from madokabot.core.resources import ResourceFolder, ResourceType, get_file
from madokabot.core.user.models import SignRecord, UserStats
from madokabot.core.user.queries import UserQueries
from madokabot.core.version import get_bot_version
from madokabot.default.shop.catalog import get_sign_template_path, get_skin_path

from .config import HTML_FILE_PATH

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def get_template_font_context(template_name: str) -> dict[str, str]:
    """只加载所选模板需要的字体，预览与正式卡片共用同一套资源。"""
    if template_name == "daily_sign_04.html":
        fonts = {
            "body_font_path": "NotoSansSC[wght].ttf",
            "number_font_path": "font.ttf",
            "title_font_path": "NotoSerifSC-Black.otf",
        }
    elif template_name in ("daily_sign_02.html", "daily_sign_03.html"):
        fonts = {
            "body_font_path": "NotoSansSC[wght].ttf",
            "latin_medium_font_path": "BarlowCondensed-Medium.ttf",
            "latin_bold_font_path": "BarlowCondensed-Bold.ttf",
        }
        if template_name == "daily_sign_02.html":
            fonts.update({
                "title_font_path": "SmileySans-Oblique.ttf",
                "latin_italic_font_path": "BarlowCondensed-BlackItalic.ttf",
            })
    else:
        fonts = {
            "font_path": "font.ttf",
            "number_font_path": "RobotoFlex.ttf",
            "english_font_path": "PlusJakartaSans.ttf",
        }
    context = {}
    for variable, filename in fonts.items():
        path = get_file(ResourceType.FONT, ResourceFolder.SIGN, filename)
        if path is None:
            raise FileNotFoundError(f"签到字体资源不存在：font/sign/{filename}")
        context[variable] = path.resolve().as_uri()
    return context


def get_template_image_context(template_name: str) -> dict[str, str]:
    """加载明日方舟模板的背景与图标图集。"""
    if template_name != "daily_sign_04.html":
        return {}
    context = {}
    for variable, filename in (
        ("background_path", "arknights/bg.png"),
        ("icons_path", "arknights/icon.png"),
    ):
        path = get_file(ResourceType.IMAGE, ResourceFolder.SIGN, filename)
        if path is None:
            raise FileNotFoundError(f"签到图片资源不存在：image/sign/{filename}")
        context[variable] = path.resolve().as_uri()
    return context


def format_rank_points(points: int) -> str:
    """排名积分格式化方法。"""
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
    """用户编号掩码方法。"""
    return f"{user_id[:2]}**{user_id[-2:]}"


async def render_sign_card(
    user_name: str,
    user: UserStats,
    sign: SignRecord,
    reward_data: dict[str, int] | None = None,
) -> MessageSegment:
    """统一准备账号数值、奖励与版本，交由所选模板渲染。"""
    template_path = get_sign_template_path(user.sign_template) or HTML_FILE_PATH
    if not template_path.is_file():
        raise FileNotFoundError(f"签到模板不存在：{HTML_FILE_PATH}")
    font_context = get_template_font_context(template_path.name)

    chara_path = get_skin_path(user.skin_asset)
    chara_display_name = None
    chara_b64 = None
    if chara_path is not None:
        chara_display_name = chara_path.stem
        image_data = base64.b64encode(chara_path.read_bytes()).decode()
        chara_b64 = f"data:image/png;base64,{image_data}"

    points_gain = None
    favor_gain = None
    continuous_delta = None
    if reward_data is not None:
        points_gain = reward_data["reward_points"] + reward_data["bonus_point"]
        favor_gain = reward_data["reward_favor"]
        continuous_delta = "+1" if sign.continuous_days > 1 else "初次"
    # 所有模板复用相同数值和格式化结果，模板只调整展示文案与布局。
    items = [
        ("总积分", f"{user.points:,}",
         f"+{points_gain}" if points_gain is not None else None),
        ("好感度", f"{user.favorability} 点",
         f"+{favor_gain}" if favor_gain is not None else None),
        ("连续陪伴", f"{sign.continuous_days} 天", continuous_delta),
        ("累计签到", f"{sign.total_count} 次", None),
    ]

    now = datetime.now(_SHANGHAI_TZ)
    async with create_session() as session:
        points_ranking = await UserQueries.get_points_ranking(session)
        daily_sign_order = await UserQueries.get_daily_sign_order(session, sign, now)
    ranking = [
        (
            nickname or "未命名",
            mask_user_id(uid),
            format_rank_points(points),
            total_count,
        )
        for uid, nickname, points, total_count in points_ranking
    ]
    current_ranking_index = next(
        (index for index, (uid, _, _, _) in enumerate(points_ranking, start=1)
         if uid == user.user_id), None,
    )
    template = Template(template_path.read_text(encoding="utf-8"), autoescape=True)
    html = template.render(
        title="每日签到" if reward_data is not None else "用户资料",
        items=items,
        points=user.points,
        favorability=user.favorability,
        continuous_days=sign.continuous_days,
        total_count=sign.total_count,
        points_gain=points_gain,
        favor_gain=favor_gain,
        bot_version=get_bot_version(),
        quote=get_sign_quote(user.favorability),
        chara_b64=chara_b64,
        chara_name=chara_display_name,
        **font_context,
        **get_template_image_context(template_path.name),
        user_name=user.display_name or user_name,
        daily_sign_order=daily_sign_order,
        user_id=mask_user_id(str(user.user_id)),
        ranking=ranking,
        current_ranking_index=current_ranking_index,
        current_time=now.strftime("%Y-%m-%d %H:%M:%S"),
    )

    image_bytes = await html_to_pic(
        html=html,
        viewport={"width": 900, "height": 600},
    )
    return MessageSegment.image(image_bytes)


def get_sign_quote(favorability: int) -> str:
    """签到台词选择方法。"""
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
