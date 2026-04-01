import time

import httpx
from nonebot import logger
from nonebot.plugin import PluginMetadata
from nonebot_plugin_alconna import Alconna, Args, Match, on_alconna

from .config import AskGeminiConfig, config


__plugin_meta__ = PluginMetadata(
    name="Gemini 问答",
    description="使用 /ask 或 /问答 调用 Gemini API 进行问答",
    usage="/ask <问题>\n/问答 <问题>",
    type="application",
    config=AskGeminiConfig,
)


ask_cmd = Alconna("ask", ["问答"], Args["question#问题", str])
ask_matcher = on_alconna(ask_cmd, priority=10, block=True)


async def _ask_gemini(question: str) -> tuple[str, int | None, float]:
    if not config.gemini_api_key:
        raise ValueError("未配置 gemini_api_key，请先在环境中填写。")

    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{config.gemini_model}:generateContent"
    payload = {
        "contents": [{"parts": [{"text": question}]}],
    }
    params = {"key": config.gemini_api_key}

    start_time = time.perf_counter()
    async with httpx.AsyncClient(timeout=config.gemini_timeout) as client:
        response = await client.post(endpoint, params=params, json=payload)
        response.raise_for_status()
        data = response.json()

    elapsed = time.perf_counter() - start_time

    candidates = data.get("candidates", [])
    if not candidates:
        raise ValueError("模型未返回可用内容。")

    parts = candidates[0].get("content", {}).get("parts", [])
    answer = "".join(part.get("text", "") for part in parts).strip()
    if not answer:
        raise ValueError("模型返回为空。")

    usage = data.get("usageMetadata", {})
    total_tokens = usage.get("totalTokenCount")

    return answer, total_tokens, elapsed


@ask_matcher.handle()
async def _(question: Match[str]):
    if not question.available or not question.result.strip():
        await ask_matcher.finish("用法：/ask <问题> 或 /问答 <问题>")

    try:
        answer, total_tokens, elapsed = await _ask_gemini(question.result.strip())
        usage_text = f"Token {total_tokens}" if total_tokens is not None else "Token 未返回"
        await ask_matcher.finish(f"{answer}\n\n📊 统计：{usage_text} | 耗时 {elapsed:.2f}s")
    except Exception as e:
        logger.exception(f"Gemini 问答失败: {e}")
        await ask_matcher.finish(f"问答失败：{e}")
