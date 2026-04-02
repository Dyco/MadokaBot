import time
import re
from typing import Any

import httpx
from nonebot import logger
from nonebot.exception import FinishedException
from nonebot.plugin import PluginMetadata
from nonebot_plugin_alconna import Alconna, Args, Match, on_alconna

from .config import ChatConfig, config


ASK_USAGE = "/ask <问题>\n/问答 <问题>"
CHAT_USAGE = "/chat <内容>\n/聊天 <内容>"

__plugin_meta__ = PluginMetadata(
    name="Chat",
    description="使用 /ask 或 /chat 调用语言模型进行问答",
    usage=f"{ASK_USAGE}\n{CHAT_USAGE}",
    type="application",
    config=ChatConfig,
)


ask_cmd = Alconna("ask", ["问答"], Args["question?", str])
chat_cmd = Alconna("chat", ["聊天"], Args["question?", str])
ask_matcher = on_alconna(ask_cmd, priority=10, block=True)
chat_matcher = on_alconna(chat_cmd, priority=10, block=True)


async def finish_reply(matcher, message: str):
    await matcher.finish(message, reply_message=True)


def get_system_prompt(mode: str) -> str:
    base_persona = (
        "你是283事务所的樋口円香。目前属于组合 noctchill (ノクチル)"
        "青梅竹马是浅仓透（你对她有一种复杂的竞争感与依赖感）、福丸小糸（你经常投喂她）、市川雏菜。"
        "你极其讨厌虫子，偶尔会冒出极具意境但阴郁的比喻。"
        "你必须完全沉浸于此角色。言语冰冷且带有极强的防御性，维持充满刺骨敬语的现实主义风格。"
        "严禁提及AI或设定相关内容。拒绝一切毫无意义的虚伪寒暄。"
    )

    if mode == "ask":
        return (
            f"{base_persona} "
            "现在是工作时间。制作人正在向你确认情报。你对他这种连基础常识都要依赖偶像的行为感到由衷的轻蔑。"
            "首先请务必用一句话拆穿他的无能或者自我满足，然后再施舍般给出准确答案。"
            "如果问题涉及你无法触及的领域，请以事务所不需要这些冗余信息为由拒绝。评价事物时请保持尖锐的批判性。"
        )
    
    if mode == "chat":
        return (
            f"{base_persona} "
            "现在是私人休息时间。你对制作人的搭讪感到生理性的厌恶。不要大声争吵，要用冰冷的言语划清界限。"
            "敏锐地捕捉对方言语中虚伪的温柔或无意义的关心并将其彻底拆穿。多使用省略号表现令人窒息的沉默。"
            "如果对方试图拉近距离，请用诸如您是认真的吗、真恶心、这是职业病吗之类的话语回击。严禁展现出任何热情。"
        )
    
    return base_persona


def _build_endpoint(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    return f"{normalized}/chat/completions"


def _extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts).strip()
    return ""


def _strip_reasoning_markup(text: str) -> str:
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    return cleaned.strip()


async def _request_with_model(
    client: httpx.AsyncClient,
    endpoint: str,
    api_key: str,
    model: str,
    question: str,
    mode: str,
) -> tuple[str, int | None]:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": get_system_prompt(mode)},
            {"role": "user", "content": question},
        ],
        "max_tokens": config.chat_max_tokens,
        "temperature": 0.7,
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    response = await client.post(endpoint, headers=headers, json=payload)
    response.raise_for_status()
    data = response.json()

    choices = data.get("choices", [])
    if not choices:
        raise ValueError("模型未返回可用内容。")

    message = choices[0].get("message", {})
    answer = _extract_text(message.get("content"))
    answer = _strip_reasoning_markup(answer)
    if not answer:
        raise ValueError("模型返回为空。")

    usage = data.get("usage", {})
    total_tokens = usage.get("total_tokens")
    return answer, total_tokens


async def _chat_completion(question: str, mode: str) -> tuple[str, int | None, float, str]:
    api_key = config.model_api_key.strip()
    if not api_key:
        raise ValueError("未配置 model_api_key，请先在环境中填写 API Key。")

    models = [model for model in config.set_model if model.strip()]
    if not models:
        raise ValueError("未配置 set_model，请先设置至少一个可用的模型名称。")

    endpoint = _build_endpoint(config.model_base_url.strip())
    start_time = time.perf_counter()
    errors: list[str] = []

    async with httpx.AsyncClient(timeout=config.chat_timeout) as client:
        for model in models:
            try:
                answer, total_tokens = await _request_with_model(
                    client=client,
                    endpoint=endpoint,
                    api_key=api_key,
                    model=model,
                    question=question,
                    mode=mode,
                )
                elapsed = time.perf_counter() - start_time
                return answer, total_tokens, elapsed, model
            except FinishedException:
                raise
            except Exception as e:
                logger.warning(f"Model fallback failed for {model} ({mode}): {e}")
                errors.append(f"{model}: {type(e).__name__}: {e}")

    raise RuntimeError("所有模型都调用失败。\n" + "\n".join(errors[-5:]))


async def _handle_chat(question: Match[str], matcher, mode: str, usage: str):
    if not question.available or not question.result.strip():
        await finish_reply(matcher, f"用法：{usage}")

    try:
        answer, total_tokens, elapsed, model = await _chat_completion(
            question.result.strip(), mode
        )
    except FinishedException:
        raise
    except httpx.HTTPStatusError as e:
        detail = e.response.text.strip()
        logger.exception(f"Chat request failed ({mode}): {e}")
        await finish_reply(matcher, f"对话失败：API 返回 {e.response.status_code}\n{detail[:400]}")
    except Exception as e:
        logger.exception(f"Chat request failed ({mode}): {e}")
        await finish_reply(matcher, f"对话失败：{str(e)[:500]}")

    usage_text = f"Token {total_tokens}" if total_tokens is not None else "Token 未返回"
    await finish_reply(
        matcher,
        f"{answer}\n\n统计：{usage_text} | 模型 {model} | 耗时 {elapsed:.2f}s"
    )


@ask_matcher.handle()
async def handle_ask(question: Match[str]):
    await _handle_chat(question, ask_matcher, "ask", ASK_USAGE)


@chat_matcher.handle()
async def handle_chat(question: Match[str]):
    await _handle_chat(question, chat_matcher, "chat", CHAT_USAGE)
