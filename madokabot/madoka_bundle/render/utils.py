import json
import random
import base64
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from jinja2 import Template
from nonebot.adapters.onebot.v11 import MessageSegment
from nonebot_plugin_htmlrender import html_to_pic
from ..registry import SKIN_MAP
from ..utils import get_file, ResType, SubFolder
from ..db.models import UserStats, SignRecord
from .config import HTML_FILE_PATH

async def render_sign_card(user_name: str, user: UserStats, sign: SignRecord, reward_data: dict = None) -> MessageSegment:
    """
    统一渲染入口
    :param user_name: 外部传入的实时昵称
    :param user: UserStats 数据库对象
    :param sign: SignRecord 数据库对象
    :param reward_data: 奖励字典，包含 reward_points, bonus_point, reward_favor
    """
    chara_path = SKIN_MAP.get(user.skin_key, SKIN_MAP["skin08"])
    font_file = get_file(ResType.FONT, SubFolder.SIGN, "font.ttf")
    font_uri = Path(font_file).as_uri() 
    chara_display_name = os.path.splitext(os.path.basename(chara_path))[0]
    
    with open(chara_path, "rb") as f:
        chara_b64 = f"data:image/png;base64,{base64.b64encode(f.read()).decode()}"

    if reward_data:
        title = "每日签到"
        points_gain = reward_data.get('reward_points', 0) + reward_data.get('bonus_point', 0)
        favor_gain = reward_data.get('reward_favor', 0)
        
        items = [
            ("总积分", f"{user.points:,}", f"+{points_gain}"),
            ("好感度", f"{user.favorability} 点", f"+{favor_gain}"),
            ("连续陪伴", f"{sign.continuous_days} 天", "+1" if sign.continuous_days > 1 else "初次"),
            ("累计签到", f"{sign.total_count} 次", None)
        ]
    else:
        title = "用户资料"
        items = [
            ("总积分", f"{user.points:,}", None),
            ("好感度", f"{user.favorability} 点", None),
            ("连续陪伴", f"{sign.continuous_days} 天", None),
            ("累计签到", f"{sign.total_count} 次", None)
        ]

    quote = await get_sign_quotes(user.favorability)
    
    if not HTML_FILE_PATH.exists():
        return MessageSegment.text("Template Missing")

    template = Template(HTML_FILE_PATH.read_text(encoding="utf-8"))
    
    html = template.render(
        title=title, 
        items=items, 
        quote=quote,
        chara_b64=chara_b64, 
        chara_name=chara_display_name,
        font_path=font_uri,
        user_name=user_name,
        user_id=str(user.user_id),     
        current_time=datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")
    )

    img_bytes = await html_to_pic(
        html=html, 
        viewport={"width": 900, "height": 600}
    )
    
    return MessageSegment.image(img_bytes)

async def get_sign_quotes(favorability: int) -> str:
    """
    根据当前时间和好感度获取樋口円香台词
    :param favorability: 用户的好感度数值
    """
    # 1. 时间段判定逻辑
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    hour = now.hour
    
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
    else: # 0-5点
        time_tag = "late night"

    if favorability < 30:
        favor_tag = "low"
    elif favorability < 60:
        favor_tag = "medium"
    else:
        favor_tag = "high"

    json_path = get_file(ResType.JSON, SubFolder.SIGN, "quotes.json")
    
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            all_quotes = json.load(f)
        
        filtered = [
            q["台词"] for q in all_quotes 
            if q["时间"] == time_tag and q["好感"] == favor_tag
        ]
        
        if filtered:
            return random.choice(filtered)
        return "……没什么好说的。"
        
    except FileNotFoundError:
        return "（找不到台词数据文件）"
    except Exception as e:
        return f"……啧，出错了。({type(e).__name__})"