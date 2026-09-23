"""douyin 链接解析事件处理器。"""

import re

import aiohttp
import httpx
from nonebot import logger
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageSegment

from ..commands import comment_mode_map as comment_mode_map_in_memory
from ..commands import resolve_controller, resolve_handler
from ..constants import (
    COMMON_HEADER,
    DOUYIN_VIDEO,
    DY_TOUTIAO_INFO,
    URL_TYPE_CODE_DICT,
)
from ..delivery import send_resolved_video
from ..matchers import (
    douyin_matcher as douyin,
)
from ..messages import (
    get_resolver_message,
    get_target_id,
    make_forward_nodes,
    send_forward,
)
from ..sources.tiktok import dou_transfer_other, generate_x_bogus_url
from ..state import is_content_enabled
from .runtime import (
    DOUYIN_PROXY,
    GLOBAL_NICKNAME,
    global_config,
)
from .video import (
    _duration_seconds,
    _skip_video_for_duration,
)


@douyin.handle()
@resolve_handler
@resolve_controller
async def dy(bot: Bot, event: GroupMessageEvent) -> None:
    """
        抖音解析
    :param bot:
    :param event:
    :return:
    """
    # 消息
    msg = get_resolver_message(event)
    logger.info(msg)
    # 短链先跟随跳转，长链直接提取视频/图集 ID。
    reg = (
        r"https?://(?:v\.douyin\.com|iesdouyin\.com|www\.douyin\.com|"
        r"douyin\.com)/[A-Za-z\d._?%&+\-=/#]*"
    )
    url_match = re.search(reg, msg, re.I)
    if not url_match:
        await douyin.finish("未识别到有效的抖音链接。")
    dou_url = url_match.group(0)
    try:
        response = httpx.get(
            dou_url,
            headers=COMMON_HEADER,
            follow_redirects=True,
            timeout=20,
            proxy=DOUYIN_PROXY,
            trust_env=False,
        )
        dou_url_2 = str(response.url)
    except httpx.HTTPError as exc:
        logger.error(f"抖音短链展开失败: {exc}")
        return

    # 实况图集临时解决方案，eg.  https://v.douyin.com/iDsVgJKL/
    if "share/slides" in dou_url_2:
        cover, author, title, images = await dou_transfer_other(
            dou_url,
            DOUYIN_PROXY,
        )
        # 如果第一个不为None 大概率是成功
        if author is not None:
            slide_segments = [
                Message(
                    [
                        MessageSegment.image(cover),
                        MessageSegment.text(
                            f"{GLOBAL_NICKNAME}识别：【抖音】\n作者：{author}\n标题：{title}"
                        ),
                    ]
                ),
                *(MessageSegment.image(url) for url in images),
            ]
            await send_forward(
                bot,
                event,
                make_forward_nodes(bot.self_id, slide_segments),
            )
        # 截断后续操作
        return
    # logger.error(dou_url_2)
    reg2 = r"(?:video|note)/(\d+)"
    # 获取到ID
    id_match = re.search(reg2, dou_url_2, re.I)
    if not id_match:
        await douyin.finish("无法从抖音链接中提取作品 ID。")
    dou_id = id_match.group(1)
    # logger.info(dou_id)
    # 如果没有设置dy的ck就结束，因为获取不到
    douyin_ck = getattr(global_config, "douyin_ck", "")
    if douyin_ck == "":
        logger.error(global_config)
        await send_forward(
            bot,
            event,
            make_forward_nodes(
                bot.self_id,
                MessageSegment.text(
                    f"{GLOBAL_NICKNAME}识别：抖音，无法获取到管理员设置的抖音ck！"
                ),
            ),
        )
        return
    # API、一些后续要用到的参数
    headers = {
        "Accept-Language": "zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2",
        "referer": f"https://www.douyin.com/video/{dou_id}",
        "cookie": douyin_ck,
    } | COMMON_HEADER
    api_url = DOUYIN_VIDEO.replace("{}", dou_id)
    try:
        api_url = generate_x_bogus_url(api_url, headers)
    except RuntimeError as exc:
        logger.error(str(exc))
        return
    async with aiohttp.ClientSession(
        proxy=DOUYIN_PROXY,
        trust_env=False,
    ) as session:
        async with session.get(api_url, headers=headers, timeout=10) as response:
            try:
                response.raise_for_status()
                response_data = await response.json()
            except (aiohttp.ClientError, ValueError) as exc:
                logger.warning(f"[抖音] 作品接口请求失败：{exc}")
                return

            if not isinstance(response_data, dict):
                logger.warning("[抖音] 作品接口返回了非对象响应")
                return
            # 获取信息
            detail = response_data.get("aweme_detail")
            if not isinstance(detail, dict):
                logger.warning(
                    f"[抖音] 作品接口缺少 aweme_detail，响应字段：{list(response_data)}"
                )
                return
            desc = detail.get("desc", "")
            # 判断是图片还是视频
            url_type_code = detail.get("aweme_type")
            url_type = URL_TYPE_CODE_DICT.get(url_type_code, "video")

            # 抖音的说明、图片和评论统一放进同一条合并转发。
            info_segment = MessageSegment.text(
                f"{GLOBAL_NICKNAME}识别：抖音\n{detail.get('desc')}"
            )
            comment_segment: MessageSegment | None = None
            comment_forward_nodes: list[MessageSegment] = []
            send_id = get_target_id(event)
            if is_content_enabled(send_id, "douyin", "comment"):
                try:
                    from ..comments import (
                        format_comments_to_nodes,
                        get_douyin_comments,
                        render_comments_image,
                    )

                    c_headers = {
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36"
                        ),
                        "referer": f"https://www.douyin.com/video/{dou_id}",
                        "cookie": douyin_ck,
                    } | COMMON_HEADER
                    author_sec_uid = detail.get("author", {}).get("sec_uid")
                    comments = await get_douyin_comments(
                        session,
                        dou_id,
                        c_headers,
                        author_sec_uid,
                    )
                    if comments:
                        mode = comment_mode_map_in_memory.get(str(send_id), "image")
                        if mode == "image":
                            try:
                                comment_bytes = await render_comments_image(
                                    comments,
                                    desc
                                    or (
                                        "抖音图集"
                                        if url_type == "image"
                                        else "抖音视频"
                                    ),
                                )
                                comment_segment = MessageSegment.image(comment_bytes)
                            except Exception as img_err:
                                logger.error(
                                    f"[Comment] 抖音图片渲染失败，自动降级为文字模式: {img_err}"
                                )
                                mode = "text"

                        if mode == "text":
                            comment_forward_nodes = format_comments_to_nodes(
                                bot.self_id,
                                comments,
                                desc
                                or ("抖音图集" if url_type == "image" else "抖音视频"),
                                GLOBAL_NICKNAME,
                            )
                except Exception as c_err:
                    logger.error(f"[Comment] 获取抖音评论失败，跳过评论节点: {c_err}")

            # 根据类型进行发送
            if url_type == "video":
                forward_nodes = list(make_forward_nodes(bot.self_id, [info_segment]))
                if comment_segment is not None:
                    forward_nodes.append(
                        make_forward_nodes(bot.self_id, comment_segment)
                    )
                forward_nodes.extend(comment_forward_nodes)
                await send_forward(bot, event, forward_nodes)

                video_data = detail.get("video")
                if not isinstance(video_data, dict):
                    logger.warning("[抖音] 作品响应缺少 video 字段")
                    return
                if _skip_video_for_duration(
                    "抖音",
                    _duration_seconds(video_data.get("duration"), milliseconds=True),
                ):
                    return
                # 识别播放地址
                play_addr = video_data.get("play_addr")
                if not isinstance(play_addr, dict) or not play_addr.get("uri"):
                    logger.warning("[抖音] 作品响应缺少 play_addr.uri")
                    return
                player_uri = str(play_addr["uri"])
                player_real_addr = DY_TOUTIAO_INFO.replace("{}", player_uri)
                # 发送视频
                # logger.info(player_addr)
                # await douyin.send(Message(MessageSegment.video(player_addr)))
                await send_resolved_video(
                    event,
                    player_real_addr,
                    DOUYIN_PROXY,
                )
            elif url_type == "image":
                # 无水印图片列表/No watermark image list
                no_watermark_image_list = []
                # 遍历图片列表/Traverse image list
                for i in detail["images"]:
                    # 无水印图片列表
                    # no_watermark_image_list.append(i['url_list'][0])
                    no_watermark_image_list.append(
                        MessageSegment.image(i["url_list"][0])
                    )
                forward_segments = [info_segment, *no_watermark_image_list]
                if comment_segment is not None:
                    forward_segments.append(comment_segment)
                forward_nodes = list(make_forward_nodes(bot.self_id, forward_segments))
                forward_nodes.extend(comment_forward_nodes)
                await send_forward(bot, event, forward_nodes)
