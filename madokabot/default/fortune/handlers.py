"""运势关键词处理与结果回复。"""

from nonebot import logger
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, MessageSegment

from madokabot.core.messaging.response import respond

from .matchers import fortune_matcher
from .render import render_fortune_card
from .service import format_reward_message, get_today_fortune


@fortune_matcher.handle()
async def handle_fortune(bot: Bot, event: MessageEvent) -> None:
    """先添加签到同款表情回应，再展示运势及每日首次奖励，图片不可用时退回文字。"""
    await respond(bot, event)
    uid = event.get_user_id()
    try:
        result, points = await get_today_fortune(uid)
    except LookupError:
        await fortune_matcher.finish("请先发送“注册”完成用户注册")
    except Exception:
        logger.exception("运势生成或积分奖励发放失败")
        await fortune_matcher.finish("运势暂时无法读取，请稍后重试")

    name = event.sender.card or event.sender.nickname or uid
    try:
        picture = await render_fortune_card(result, uid, name)
        message = MessageSegment.text("今日运势\n") + picture
    except Exception:
        logger.exception("运势卡片渲染失败，改用文字回复")
        message = MessageSegment.text(result.as_text())
    if points > 0:
        message += MessageSegment.text("\n" + format_reward_message(result.level, points))
    await fortune_matcher.finish(message)
