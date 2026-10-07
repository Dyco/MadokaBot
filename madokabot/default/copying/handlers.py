from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from nonebot.adapters import Bot, Event, Message
from nonebot.plugin import on_message
from nonebot_plugin_alconna import (
    Alconna,
    Args,
    Arparma,
    CommandMeta,
    Subcommand,
    on_alconna,
)

from madokabot.core.group.access import is_group_whitelisted
from madokabot.core.group.settings import group_settings
from .config import config

# 控制命令不能计入复读记录。
copying = on_message(priority=20, block=False)

copying_switch_command = Alconna(
    "copying",
    Subcommand("on", alias=["开", "开启"]),
    Subcommand("off", alias=["关", "关闭"]),
    Subcommand("set", Args["number", int], alias=["设置"]),
    meta=CommandMeta(compact=True),
)

copying_switch_matcher = on_alconna(
    copying_switch_command,
    use_cmd_start=True,
    aliases={"复读", "复读机"},
    priority=10,
    block=True,
)


copying_number = config.copying_number
_GROUP_SETTINGS_NAME = "group_set"


@dataclass
class _CopyingState:
    """群连续消息状态。"""

    last_message: Message | None = None
    repeat_count: int = 0
    threshold: int = 1
    echoed: bool = False


msg_dict: dict[str, _CopyingState] = {}

_COPYABLE_SEGMENT_TYPES = {"text", "image"}
_IMAGE_ID_KEYS = (
    "file_unique",
    "file_id",
    "md5",
    "hash",
    "file",
    "url",
    "id",
)


def _freeze(value: Any) -> Any:
    """把消息段数据转换成可比较的稳定结构。"""

    if isinstance(value, dict):
        return tuple(
            sorted(
                ((str(key), _freeze(item)) for key, item in value.items()),
                key=lambda item: item[0],
            )
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze(item) for item in value)
    if isinstance(value, bytearray):
        return bytes(value)

    try:
        hash(value)
    except TypeError:
        return repr(value)
    return value


def _image_identity_values(segment: Any) -> set[Any]:
    """图片标识提取方法。"""

    data = getattr(segment, "data", {})
    return {
        _freeze(data[key])
        for key in _IMAGE_ID_KEYS
        if key in data and data[key] not in (None, "")
    }


def _image_equal(segment1: Any, segment2: Any) -> bool:
    """图片消息比较方法。"""

    identity1 = _image_identity_values(segment1)
    identity2 = _image_identity_values(segment2)
    if identity1 and identity2:
        return bool(identity1 & identity2)

    # 缺少稳定标识时比较完整数据，不能只比较文件大小。
    return _freeze(getattr(segment1, "data", {})) == _freeze(
        getattr(segment2, "data", {})
    )


def _segment_equal(segment1: Any, segment2: Any) -> bool:
    if getattr(segment1, "type", None) != getattr(segment2, "type", None):
        return False
    if getattr(segment1, "type", None) == "image":
        return _image_equal(segment1, segment2)
    return _freeze(getattr(segment1, "data", {})) == _freeze(
        getattr(segment2, "data", {})
    )


def is_equal(msg1: Message, msg2: Message) -> bool:
    """判断两条消息的内容是否相同。"""

    if len(msg1) != len(msg2):
        return False
    return all(_segment_equal(left, right) for left, right in zip(msg1, msg2))


def _get_group_id(event: Event) -> str | None:
    group_id = getattr(event, "group_id", None)
    if group_id is None:
        return None
    group_id = str(group_id).strip()
    return group_id or None


def _default_group_settings() -> dict[str, Any]:
    """返回复读机群组设置的默认值。"""

    return {
        "copying_enabled": True,
        "threshold": copying_number,
    }


def _get_group_settings(group_id: str) -> dict[str, Any]:
    """复读群设置读取方法。"""

    settings = group_settings.get(group_id, _GROUP_SETTINGS_NAME)
    if not isinstance(settings, dict):
        settings = _default_group_settings()
        group_settings.set(group_id, _GROUP_SETTINGS_NAME, settings)
    return settings


def _get_threshold(settings: dict[str, Any]) -> int:
    # 手动修改群配置可能绕过阈值校验。
    threshold = settings.get("threshold", copying_number)
    if not isinstance(threshold, int):
        return max(1, copying_number)
    return max(1, threshold)


def _is_copyable(message: Message) -> bool:
    """复读消息类型检查方法。"""

    return bool(message) and all(
        segment.type in _COPYABLE_SEGMENT_TYPES for segment in message
    )


def _reset_group_state(group_id: str) -> None:
    msg_dict.pop(group_id, None)


@copying_switch_matcher.handle()
async def handle_copying_switch(event: Event, result: Arparma):
    group_id = _get_group_id(event)
    if group_id is None:
        await copying_switch_matcher.finish("复读机指令只能在群聊中使用。")

    if not is_group_whitelisted(group_id):
        await copying_switch_matcher.finish("该群未在白名单中，无法使用复读机功能。")

    settings = _get_group_settings(group_id)

    if "on" in result.subcommands:
        settings["copying_enabled"] = True
        group_settings.set(group_id, _GROUP_SETTINGS_NAME, settings)
        _reset_group_state(group_id)
        await copying_switch_matcher.finish(
            f"复读机已开启，当前连续 {_get_threshold(settings)} 条相同消息时触发。"
        )

    if "off" in result.subcommands:
        settings["copying_enabled"] = False
        group_settings.set(group_id, _GROUP_SETTINGS_NAME, settings)
        _reset_group_state(group_id)
        await copying_switch_matcher.finish("复读机已关闭。")

    if "set" in result.subcommands:
        number = result.query("set.args.number", None)
        if not isinstance(number, int) or number < 1:
            await copying_switch_matcher.finish("复读机设置的消息数量必须大于等于1。")

        settings["threshold"] = number
        group_settings.set(group_id, _GROUP_SETTINGS_NAME, settings)
        _reset_group_state(group_id)
        await copying_switch_matcher.finish(
            f"复读机已设置为连续 {number} 条相同消息时触发。"
        )

    await copying_switch_matcher.finish(
        "用法：复读 开/开启、复读 关/关闭，或复读 设置 <数量>。"
    )


@copying.handle()
async def handle_copying(bot: Bot, event: Event):
    group_id = _get_group_id(event)
    if group_id is None:
        return

    # 忽略机器人自身事件，防止复读回路。
    user_id = getattr(event, "user_id", None)
    self_id = getattr(bot, "self_id", None)
    if user_id is not None and self_id is not None and str(user_id) == str(self_id):
        return

    if not is_group_whitelisted(group_id):
        _reset_group_state(group_id)
        return

    settings = _get_group_settings(group_id)
    if not settings.get("copying_enabled", True):
        return

    message = event.get_message()
    if not _is_copyable(message):
        # 其他消息类型也会打断连续复读。
        _reset_group_state(group_id)
        return

    threshold = _get_threshold(settings)
    state = msg_dict.get(group_id)
    if state is None or state.threshold != threshold:
        state = _CopyingState(threshold=threshold)
        msg_dict[group_id] = state

    if state.last_message is not None and is_equal(state.last_message, message):
        state.repeat_count = min(state.repeat_count + 1, threshold)
        # 图片标识可能轮换，连续判断需比较紧邻消息。
        state.last_message = deepcopy(message)
    else:
        state.last_message = deepcopy(message)
        state.repeat_count = 1
        state.echoed = False

    if state.repeat_count >= threshold and not state.echoed:
        state.echoed = True
        await copying.send(message)
