"""聊天参数校验、失败提示和回答发送。"""

from nonebot import logger
from nonebot_plugin_alconna import Match

from .client import chat_completion
from .matchers import ASK_USAGE, CHAT_USAGE, ask_matcher, chat_matcher


async def finish_reply(matcher, message: str):
    """引用原消息发送回复并结束当前会话。"""
    await matcher.finish(message, reply_message=True)


async def _handle_chat(question: Match[str], matcher, mode: str, usage: str):
    """校验问题，调用模型并发送回答及用量统计。"""
    if not question.available or not question.result.strip():
        await finish_reply(matcher, f"用法：{usage}")

    try:
        answer, total_tokens, elapsed, model = await chat_completion(
            question.result.strip(), mode
        )
    except (RuntimeError, ValueError) as exc:
        logger.error(f"Chat request failed ({mode}): {exc}")
        await finish_reply(matcher, f"对话失败：{str(exc)[:500]}")

    usage_text = f"Token {total_tokens}" if total_tokens is not None else "Token 未返回"
    await finish_reply(
        matcher,
        f"{answer}\n\n统计：{usage_text} | 模型 {model} | 耗时 {elapsed:.2f}s"
    )


@ask_matcher.handle()
async def handle_ask(question: Match[str]):
    """处理问答命令。"""
    await _handle_chat(question, ask_matcher, "ask", ASK_USAGE)


@chat_matcher.handle()
async def handle_chat(question: Match[str]):
    """处理闲聊命令。"""
    await _handle_chat(question, chat_matcher, "chat", CHAT_USAGE)
