"""聊天参数校验、失败提示和回答发送。"""

from nonebot import logger
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent
from nonebot_plugin_alconna import Match

from madokabot.core.group.access import is_group_whitelisted
from madokabot.core.user.accounts import UserAccount

from .client import chat_completion
from .matchers import ASK_USAGE, CHAT_USAGE, ask_matcher, chat_matcher
from .service import deduct_chat_point


async def finish_reply(matcher, message: str):
    """会话回复方法。"""
    await matcher.finish(message, reply_message=True)


async def _handle_chat(
    event: MessageEvent, question: Match[str], matcher, mode: str, usage: str
):
    """校验群权限和积分，调用模型后收取费用并发送回答。"""
    if not isinstance(event, GroupMessageEvent):
        await finish_reply(matcher, "该指令只能在白名单群中使用。")
    if not is_group_whitelisted(event.group_id):
        await finish_reply(matcher, "本群不在白名单里，无法使用，请联系机器人管理员。")

    uid = event.get_user_id()
    try:
        points = await UserAccount.get_points(uid)
    except LookupError:
        await finish_reply(matcher, "你尚未注册，无法使用，请先发送“注册”完成用户注册。")
    if points <= 0:
        await finish_reply(matcher, "积分不足，无法使用，调用需要1积分。")

    if not question.available or not question.result.strip():
        await finish_reply(matcher, f"用法：{usage}")

    try:
        answer, total_tokens, elapsed, model = await chat_completion(
            question.result.strip(), mode
        )
    except (RuntimeError, ValueError) as exc:
        logger.error(f"Chat request failed ({mode}): {exc}")
        await finish_reply(matcher, f"对话失败：{str(exc)[:500]}\n本次未收取积分。")

    if not await deduct_chat_point(uid):
        await finish_reply(matcher, "积分余额已不足，无法完成本次对话，本次未收取积分。")

    usage_text = f"Token {total_tokens}" if total_tokens is not None else "Token 未返回"
    await finish_reply(
        matcher,
        f"{answer}\n\n统计：{usage_text} | 模型 {model} | 耗时 {elapsed:.2f}s\n已收取1积分"
    )


@ask_matcher.handle()
async def handle_ask(event: MessageEvent, question: Match[str]):
    """处理问答命令。"""
    await _handle_chat(event, question, ask_matcher, "ask", ASK_USAGE)


@chat_matcher.handle()
async def handle_chat(event: MessageEvent, question: Match[str]):
    """处理闲聊命令。"""
    await _handle_chat(event, question, chat_matcher, "chat", CHAT_USAGE)
