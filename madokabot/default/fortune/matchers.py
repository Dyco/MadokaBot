"""运势匹配关键词。"""

from nonebot import on_message
from nonebot.rule import fullmatch

fortune_matcher = on_message(
    rule=fullmatch(("运势", "/运势","fortune","/fortune")), priority=10, block=True
)
