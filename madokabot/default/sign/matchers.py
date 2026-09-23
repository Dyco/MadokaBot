"""签到完整匹配命令。"""

from nonebot import on_message
from nonebot.rule import fullmatch

sign_keywords: list[str] = ["打卡", "签到", "sign"]
sign_matcher = on_message(
    rule=fullmatch(sign_keywords),
    priority=10,
    block=True,
)
