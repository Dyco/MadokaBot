"""许愿关键词处理与结果回复。"""

from nonebot import logger
from nonebot.adapters.onebot.v11 import MessageEvent

from .matchers import wish_matcher
from .service import execute_wish


@wish_matcher.handle()
async def handle_wish(event: MessageEvent) -> None:
    """使用发送者账号许愿并回复结算结果。"""
    try:
        message = await execute_wish(event.get_user_id())
    except Exception:
        logger.exception("许愿处理失败")
        message = "许愿暂时无法处理，请稍后重试"
    await wish_matcher.finish(message)
