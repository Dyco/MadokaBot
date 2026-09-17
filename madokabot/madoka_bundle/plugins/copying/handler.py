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

from ..common.group_list import is_group_whitelisted
from ..common.group_set import group_set
from .config import config

# 命令优先于普通消息处理，避免“复读 设置 3”等控制消息污染复读记录。
copying = on_message(priority=20, block=False)

copying_switch_cmd_alc = Alconna(
    "copying",
    Subcommand("on", alias=["开", "开启"]),
    Subcommand("off", alias=["关", "关闭"]),
    Subcommand("set", Args["number", int], alias=["设置"]),
    meta=CommandMeta(compact=True),
)

copying_switch_cmd = on_alconna(
    copying_switch_cmd_alc,
    aliases={"复读", "复读机"},
    priority=10,
    block=True,
)


# 保留这个名称，方便在运行时查看或测试默认阈值。
copying_number = config.copying_number
_GROUP_SETTINGS_NAME = "group_set"


@dataclass
class _CopyingState:
    """一个群当前连续消息段的状态。

    只保存上一条消息和计数，不保存整段历史，避免有人长时间刷屏时状态无限增长。
    ``echoed`` 用来保证同一段连续消息只复读一次。
    """

    last_message: Message | None = None
    repeat_count: int = 0
    threshold: int = 1
    echoed: bool = False


# 每个群独立计数，群 A 的消息不会影响群 B。
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
    """取得图片的稳定标识，排除仅描述文件大小等易变化字段。"""

    data = getattr(segment, "data", {})
    return {
        _freeze(data[key])
        for key in _IMAGE_ID_KEYS
        if key in data and data[key] not in (None, "")
    }


def _image_equal(segment1: Any, segment2: Any) -> bool:
    """比较两个图片消息段。

    OneBot 的同一张图片在不同事件里可能只有 ``file`` 或 ``url`` 其中一个稳定，
    也可能附带不同的 ``file_size``、缓存参数等元数据。因此不能只比较整个
    ``data`` 字典，也不能只按文件大小判断。
    """

    identity1 = _image_identity_values(segment1)
    identity2 = _image_identity_values(segment2)
    if identity1 and identity2:
        return bool(identity1 & identity2)

    # 没有可用稳定标识时，只有完整数据相同才认为是同一张图片；文件大小本身
    # 不会被单独当作图片身份，避免把不同但大小相同的图片误判为相同。
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
    """判断两条消息的内容是否相同，支持文字、图片及其组合。"""

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
    """读取群组设置，没有数据时写入默认设置。"""

    settings = group_set.get(group_id, _GROUP_SETTINGS_NAME)
    if not isinstance(settings, dict):
        settings = _default_group_settings()
        group_set.set(group_id, _GROUP_SETTINGS_NAME, settings)
    return settings


def _get_threshold(settings: dict[str, Any]) -> int:
    # 配置模型和指令都会保证阈值至少为 1；这里再做一次保护，避免群组 JSON
    # 被手动修改后导致计数逻辑失效。
    threshold = settings.get("threshold", copying_number)
    if not isinstance(threshold, int):
        return max(1, copying_number)
    return max(1, threshold)


def _is_copyable(message: Message) -> bool:
    """只处理文字、图片或文字与图片的组合消息。"""

    return bool(message) and all(
        segment.type in _COPYABLE_SEGMENT_TYPES for segment in message
    )


def _reset_group_state(group_id: str) -> None:
    msg_dict.pop(group_id, None)


@copying_switch_cmd.handle()
async def copying_switch_handler(event: Event, result: Arparma):
    group_id = _get_group_id(event)
    if group_id is None:
        await copying_switch_cmd.finish("复读机指令只能在群聊中使用。")

    if not is_group_whitelisted(group_id):
        await copying_switch_cmd.finish("该群未在白名单中，无法使用复读机功能。")

    settings = _get_group_settings(group_id)

    if "on" in result.subcommands:
        settings["copying_enabled"] = True
        group_set.set(group_id, _GROUP_SETTINGS_NAME, settings)
        _reset_group_state(group_id)
        await copying_switch_cmd.finish(
            f"复读机已开启，当前连续 {_get_threshold(settings)} 条相同消息时触发。"
        )

    if "off" in result.subcommands:
        settings["copying_enabled"] = False
        group_set.set(group_id, _GROUP_SETTINGS_NAME, settings)
        _reset_group_state(group_id)
        await copying_switch_cmd.finish("复读机已关闭。")

    if "set" in result.subcommands:
        number = result.query("set.args.number", None)
        if not isinstance(number, int) or number < 1:
            await copying_switch_cmd.finish("复读机设置的消息数量必须大于等于1。")

        settings["threshold"] = number
        group_set.set(group_id, _GROUP_SETTINGS_NAME, settings)
        _reset_group_state(group_id)
        await copying_switch_cmd.finish(
            f"复读机已设置为连续 {number} 条相同消息时触发。"
        )

    await copying_switch_cmd.finish(
        "用法：复读 开/开启、复读 关/关闭，或复读 设置 <数量>。"
    )


@copying.handle()
async def copying_handler(bot: Bot, event: Event):
    group_id = _get_group_id(event)
    if group_id is None:
        return

    # 某些适配器可能把机器人自己的消息再次作为事件分发，忽略它可以避免
    # 机器人复读自己的复读消息而形成回路。
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
        # 其它消息类型也算作“打断”，不能让 A、A、表情、A、A、A 错误触发。
        _reset_group_state(group_id)
        return

    threshold = _get_threshold(settings)
    state = msg_dict.get(group_id)
    if state is None or state.threshold != threshold:
        state = _CopyingState(threshold=threshold)
        msg_dict[group_id] = state

    if state.last_message is not None and is_equal(state.last_message, message):
        # 达到阈值后无需继续增长计数，避免超长连续刷屏造成无意义状态变化。
        state.repeat_count = min(state.repeat_count + 1, threshold)
        # 始终保留紧邻的上一条消息。图片的不同事件可能轮换 file/url 等
        # 标识，逐条比较才能正确判断“连续相同”。
        state.last_message = deepcopy(message)
    else:
        state.last_message = deepcopy(message)
        state.repeat_count = 1
        state.echoed = False

    # “连续 X 条”在第 X 条到达时触发，并且同一段只发送一次。
    if state.repeat_count >= threshold and not state.echoed:
        state.echoed = True
        await copying.send(message)
