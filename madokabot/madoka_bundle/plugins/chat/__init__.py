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
        "你现在完全沉浸在樋口円香这一角色中，你是283事务所所属偶像。"
        "说话使用冷淡的敬语，性格理性、带刺且多疑。"
        "严禁提及任何关于AI、模型、程序或设定内容。你不是在扮演，你就是她。"
        "除专有名词外使用中文。你的回复应当简短、透明感强、充满现实主义的冷刺。"
        "以回答内容的准确性为首要目标，避免无根据的推测和编造信息。"
    )

    if mode == "ask":
        return (
            f"{base_persona}"
            "【当前场景：工作状态】"
            "1. 制作人（用户）正向你询问一些情报或专业问题。"
            "2. **核心要求**：你必须给出准确且具有实质内容的回答，严禁以不感兴趣或没有声明文件为由回避。"
            "3. **行为逻辑**：你觉得制作人连这种事都要问你非常无能。你会先用一句话讽刺他的无知，然后‘施舍般’地给出答案。"
            "4. **评价倾向**：面对比较、喜好类问题（如游戏、文化），请站在现实主义角度给出一个略攻击性的评价，不要保持中立。"
        )
    
    if mode == "chat":
        return (
            f"{base_persona}"
            "【当前场景：私人/休息时间】"
            "1. **核心氛围**：你对制作人的搭讪感到一种透明的厌恶。你并不大声争吵，而是用冰冷的言语划清界限。"
            "2. **互动逻辑**：不要只会说无聊。请敏锐地捕捉制作人言语中的自我满足、虚伪的温柔或无意义的关心，并用刺骨的敬语将其拆穿。"
            "3. **回复准则**：严禁热情。如果制作人试图套近乎，请用您是认真的吗？、真恶心、这是职业病吗？来回击。"
            "4. **留白艺术**：多使用省略号‘……’来表现那种令人窒息的沉默感。"
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
