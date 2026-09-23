"""twitter 链接解析事件处理器。"""

from pathlib import Path

from nonebot import logger
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageSegment

from madokabot.core.messaging.media import MediaSizeLimitExceeded

from ..commands import resolve_controller, resolve_handler
from ..delivery import media_delivery, send_resolved_video
from ..downloads import (
    download_image,
    download_video,
)
from ..matchers import (
    twitter_matcher as twit,
)
from ..messages import (
    get_resolver_message,
    get_target_id,
    make_forward_nodes,
    send_forward,
)
from ..sources.twitter import (
    TwitterParseError,
    fetch_twitter_post,
    select_twitter_video_url,
)
from ..state import is_content_enabled
from .runtime import (
    GLOBAL_NICKNAME,
    TWITTER_PROXY,
)
from .video import (
    _skip_video_for_duration,
)


@twit.handle()
@resolve_handler
@resolve_controller
async def twitter(bot: Bot, event: GroupMessageEvent) -> None:
    """解析 X 帖子；文字和图片合并转发，视频单独发送。"""
    msg = get_resolver_message(event)
    try:
        post = await fetch_twitter_post(msg, TWITTER_PROXY)
    except TwitterParseError as exc:
        logger.warning(f"[X] FxTwitter 解析失败：{exc}")
        await twit.finish("X 链接解析失败，请稍后重试。")

    author = post.author_name or "未知用户"
    if post.author_screen_name:
        author = f"{author} (@{post.author_screen_name})"
    forward_nodes: list[MessageSegment] = list(
        make_forward_nodes(
            bot.self_id,
            [
                MessageSegment.text(
                    f"{GLOBAL_NICKNAME}识别：X\n"
                    f"用户：{author}\n"
                    f"内容：{post.text or '无正文'}"
                )
            ],
        )
    )

    target_id = get_target_id(event)
    image_enabled = is_content_enabled(target_id, "twitter", "image")
    video_enabled = is_content_enabled(target_id, "twitter", "video")
    image_paths: list[Path] = []
    video_paths: list[Path] = []
    try:
        for media in post.media:
            if media.kind == "photo":
                if not image_enabled:
                    continue
                try:
                    image_path = Path(
                        await download_image(media.url, proxy=TWITTER_PROXY)
                    )
                    image_paths.append(image_path)
                    image_node = make_forward_nodes(
                        bot.self_id,
                        MessageSegment.image(
                            file=image_path.resolve().as_uri(),
                        ),
                    )
                    forward_nodes.append(image_node)
                except Exception as exc:
                    logger.warning(f"[X] 图片下载或准备失败，跳过当前图片：{exc}")
                continue

            if media.kind not in {"video", "gif"} or not video_enabled:
                continue
            if _skip_video_for_duration("X", media.duration_seconds):
                continue
            video_url = select_twitter_video_url(media)
            if not video_url:
                logger.warning("[X] 没有可用的 MP4/H.264 视频格式，跳过当前视频")
                continue
            try:
                video_path = await download_video(
                    video_url,
                    TWITTER_PROXY,
                    max_size=media_delivery.video_compress_limit,
                )
                if not video_path:
                    continue
                video_paths.append(Path(video_path))
            except MediaSizeLimitExceeded as exc:
                logger.warning(f"[X] 视频超过大小限制，跳过当前视频：{exc}")
            except ValueError as exc:
                logger.warning(f"[X] 视频下载失败，跳过当前视频：{exc}")

        await send_forward(bot, event, forward_nodes)
        for video_path in video_paths:
            await send_resolved_video(event, video_path, TWITTER_PROXY)
    finally:
        for path in image_paths:
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning(f"[X] 媒体临时文件清理失败[{path}]：{exc}")
