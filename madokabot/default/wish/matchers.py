"""许愿完整匹配关键词。"""

from nonebot import on_message
from nonebot.rule import fullmatch

wish_matcher = on_message(rule=fullmatch("许愿"), priority=10, block=True)
