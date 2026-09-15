"""为 OneBot V11 消息提供统一的表情回应工具。"""

from dataclasses import dataclass

from nonebot import logger
from nonebot.adapters.onebot.v11 import Bot, MessageEvent

from .config import config


def _resolve_emoji_id(
    emoji_id: str | int | None,
    default_emoji_id: str,
) -> str:
    """优先使用调用方传入的表情 ID，空值时回退到默认值。"""
    value = "" if emoji_id is None else str(emoji_id).strip()
    return value or str(default_emoji_id).strip()


def _get_message_id(event: MessageEvent) -> int | None:
    """读取消息事件的消息 ID，读取失败时返回空值。"""
    value = getattr(event, "message_id", None)
    try:
        message_id = int(value)
    except (TypeError, ValueError):
        logger.warning(f"无法读取消息回应所需的消息 ID：{value!r}")
        return None
    return message_id


async def _set_message_emoji(
    bot: Bot,
    message_id: int,
    emoji_id: str,
    *,
    is_set: bool,
) -> bool:
    """调用 OneBot 扩展添加或移除消息表情回应。"""
    emoji_id = str(emoji_id).strip()
    if not emoji_id:
        logger.warning("消息回应表情 ID 为空，跳过表情回应")
        return False

    try:
        await bot.call_api(
            "set_msg_emoji_like",
            message_id=message_id,
            emoji_id=emoji_id,
            set=is_set,
        )
    except Exception as exc:
        action = "添加" if is_set else "移除"
        logger.warning(
            f"{action}消息表情回应失败：message_id={message_id}，"
            f"emoji_id={emoji_id}，{exc}"
        )
        return False
    return True


@dataclass
class StatusResponse:
    """记录一次状态回应，并负责将其切换为完成状态。"""

    bot: Bot
    message_id: int
    response_emoji_id: str
    complete_emoji_id: str
    _completed: bool = False

    async def complete(self, emoji_id: str | int | None = None) -> bool:
        """将状态回应更新为完成表情，空参数时使用创建时的默认值。"""
        if self._completed:
            return True

        complete_emoji_id = _resolve_emoji_id(emoji_id, self.complete_emoji_id)
        if self.response_emoji_id == complete_emoji_id:
            self._completed = True
            return True

        completed = await _set_message_emoji(
            self.bot,
            self.message_id,
            complete_emoji_id,
            is_set=True,
        )
        if not completed:
            return False

        removed = await _set_message_emoji(
            self.bot,
            self.message_id,
            self.response_emoji_id,
            is_set=False,
        )
        self._completed = removed
        return removed


async def respond(
    bot: Bot,
    event: MessageEvent,
    emoji_id: str | int | None = None,
) -> bool:
    """给收到的消息添加一次性回应，空表情参数时使用配置默认值。"""
    message_id = _get_message_id(event)
    if message_id is None:
        return False
    return await _set_message_emoji(
        bot,
        message_id,
        _resolve_emoji_id(emoji_id, config.response_emoji_id),
        is_set=True,
    )


async def respond_with_status(
    bot: Bot,
    event: MessageEvent,
    response_emoji_id: str | int | None = None,
    complete_emoji_id: str | int | None = None,
) -> StatusResponse | None:
    """先添加状态回应，空参数分别回退到配置中的开始和完成表情。"""
    message_id = _get_message_id(event)
    if message_id is None:
        return None

    response_emoji_id = _resolve_emoji_id(
        response_emoji_id,
        config.status_response_emoji_id,
    )
    complete_emoji_id = _resolve_emoji_id(
        complete_emoji_id,
        config.status_complete_emoji_id,
    )
    started = await _set_message_emoji(
        bot,
        message_id,
        response_emoji_id,
        is_set=True,
    )
    if not started:
        return None

    return StatusResponse(
        bot=bot,
        message_id=message_id,
        response_emoji_id=response_emoji_id,
        complete_emoji_id=complete_emoji_id,
    )
