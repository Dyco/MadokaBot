from __future__ import annotations

from nonebot import logger
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot_plugin_alconna import (
    Alconna,
    Args,
    Arparma,
    CommandMeta,
    Image,
    Match,
    Subcommand,
    on_alconna,
)

from .render import normalize_template_id, render_music_card
from .service import cleanup_image, prepare_image

PIC_USAGE = "用法：/制图 音乐 <图片> [模板 1-4] [标题] [子标题]"

picture_command = Alconna(
    "pic",
    Subcommand(
        "music",
        Args["image?", Image],
        Args["template?", str],
        Args["title?", str],
        Args["subtitle?", str],
        alias=["Music", "音乐"],
        help_text="使用音乐模板生成图片",
    ),
    separators=" ",
    meta=CommandMeta(compact=True),
)

pic = on_alconna(
    picture_command,
    aliases={"pic", "/pic", "制图", "/制图"},
    use_cmd_start=False,
    use_cmd_sep=False,
    priority=10,
    block=True,
)


def _match_text(value: Match[str], default: str) -> str:
    """读取可选文本参数，空文本时使用默认值。"""
    if not value.available:
        return default
    return value.result.strip() or default


@pic.handle()
async def handle_picture_root(result: Arparma) -> None:
    """处理没有提供音乐子指令的制图命令。"""
    if not result.subcommands:
        await pic.finish(PIC_USAGE)


@pic.assign("music")
async def handle_music(
    event: MessageEvent,
    image: Match[Image],
    template: Match[str],
    title: Match[str],
    subtitle: Match[str],
) -> None:
    """接收音乐制图参数并生成图片。"""
    if not image.available or image.result is None:
        await pic.finish(PIC_USAGE)

    user_id = event.get_user_id()
    display_name = (
        getattr(event.sender, "card", "")
        or getattr(event.sender, "nickname", "")
        or user_id
    ).strip()

    try:
        template_id = normalize_template_id(
            template.result if template.available else None
        )
    except ValueError as exc:
        await pic.finish(str(exc))

    prepared = None
    try:
        prepared = await prepare_image(image.result)
        result = await render_music_card(
            prepared,
            template_id,
            title=_match_text(title, display_name),
            subtitle=_match_text(subtitle, user_id),
            author=display_name,
            user_id=user_id,
        )
    except ValueError as exc:
        await pic.finish(f"图片处理失败：{exc}")
    except Exception:
        logger.exception("音乐制图失败")
        await pic.finish("图片生成失败，请稍后重试。")
    finally:
        if prepared is not None:
            cleanup_image(prepared)

    await pic.finish(result)
