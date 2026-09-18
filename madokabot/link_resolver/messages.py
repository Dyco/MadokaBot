"""Resolver 的 OneBot 消息构造与目标选择。"""

from pathlib import Path

from nonebot import get_plugin_config, logger
from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupMessageEvent,
    Message,
    MessageSegment,
)

from .config import Config
from .delivery import media_delivery
from .state import (
    current_resolver_key,
    current_resolver_target,
    is_content_enabled,
)

NICKNAME = get_plugin_config(Config).global_prefix_nickname.strip()
IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".gif"})
VIDEO_SUFFIXES = frozenset({".mp4", ".mov", ".webm"})


def get_resolver_message(event: GroupMessageEvent) -> str:
    """返回可供解析器检查的文本，不包含图片和语音消息段。"""
    return str(event.get_message().exclude("image", "record")).strip()


def build_media_node(
    user_id: int | str,
    task: str | Path | None,
) -> MessageSegment | None:
    """按本地文件后缀构造合并转发节点。"""
    if not task:
        return None

    path = Path(task)
    suffix = path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        content = MessageSegment.image(file=path.resolve().as_uri())
    elif suffix in VIDEO_SUFFIXES:
        content = MessageSegment.video(file=path.resolve().as_uri())
    else:
        return None

    return MessageSegment.node_custom(
        user_id=user_id,
        nickname=NICKNAME,
        content=Message(content),
    )


def make_forward_nodes(
    user_id: int | str,
    segments: Message | MessageSegment | list,
) -> MessageSegment | list[MessageSegment]:
    """将消息段包装成 OneBot 合并转发节点。"""

    def make_node(segment: Message | MessageSegment) -> MessageSegment:
        content = segment if isinstance(segment, Message) else Message(segment)
        return MessageSegment.node_custom(
            user_id=user_id,
            nickname=NICKNAME,
            content=content,
        )

    if isinstance(segments, list):
        return [make_node(segment) for segment in segments]
    return make_node(segments)


def _build_forward_fallback(messages: list[MessageSegment]) -> str:
    """提取合并转发中的文字，作为媒体发送失败时的降级内容。"""
    texts: list[str] = []
    for node in messages:
        content = node.data.get("content")
        if isinstance(content, Message):
            text = content.extract_plain_text().strip()
            if text:
                texts.append(text)

    if texts:
        return (
            "\n".join(texts)
            + "\n\n⚠️ 合并转发发送失败，图片/媒体内容已省略。"
        )
    return "⚠️ 合并转发发送失败，图片/媒体内容暂时无法发送，请稍后重试。"


def _filter_disabled_images(
    messages: list[MessageSegment],
) -> list[MessageSegment]:
    """按当前群组设置移除被关闭的解析图片。"""
    resolver_key = current_resolver_key.get()
    target_id = current_resolver_target.get()
    if (
        resolver_key is None
        or is_content_enabled(target_id, resolver_key, "image")
    ):
        return messages

    filtered: list[MessageSegment] = []
    for segment in messages:
        if segment.type == "image":
            continue
        if segment.type != "node":
            filtered.append(segment)
            continue

        content = segment.data.get("content")
        if not isinstance(content, Message):
            filtered.append(segment)
            continue
        content = content.exclude("image")
        if not content:
            continue

        user_id = segment.data.get("user_id")
        nickname = segment.data.get("nickname")
        if user_id is None or nickname is None:
            filtered.append(segment)
            continue
        filtered.append(
            MessageSegment.node_custom(
                user_id=user_id,
                nickname=nickname,
                content=content,
            )
        )
    return filtered


async def send_forward(
    bot: Bot,
    event: GroupMessageEvent,
    segments: MessageSegment | list,
) -> None:
    """向群聊发送合并转发。"""
    messages = segments if isinstance(segments, list) else [segments]
    messages = _filter_disabled_images(messages)
    if not messages:
        logger.info("当前群组已关闭该 Resolver 的图片内容，跳过合并转发")
        return
    try:
        await bot.send_group_forward_msg(
            group_id=event.group_id,
            messages=messages,
        )
    except Exception as exc:
        logger.warning(f"合并转发发送失败，已降级为普通文本：{exc}")
        await bot.send(event, _build_forward_fallback(messages))


async def upload_file(
    bot: Bot,
    event: GroupMessageEvent,
    file_path: str | Path,
    name: str,
) -> None:
    """通过通用媒体服务向事件目标上传文件。"""
    media = media_delivery.inspect(file_path, name)
    await media_delivery.upload_file(bot, event, media)


def get_target_id(event: GroupMessageEvent) -> int:
    """获取当前群组 ID。"""
    return event.group_id
