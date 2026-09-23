"""bilibili 链接解析事件处理器。"""

import re
import shutil
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import aiohttp
import httpx
from nonebot import logger
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageSegment

from madokabot.core.config import config as madoka_config
from madokabot.core.messaging.media import MediaSizeLimitExceeded

from ..commands import comment_mode_map as comment_mode_map_in_memory
from ..commands import resolve_controller, resolve_handler
from ..constants import (
    BILIBILI_HEADER,
)
from ..delivery import media_delivery, send_resolved_video
from ..downloads import (
    CACHE_DIR,
    DownloadBudget,
    clean_title,
    ensure_remote_total_within_limit,
)
from ..matchers import (
    bilibili_matcher as bili23,
)
from ..messages import (
    get_resolver_message,
    get_target_id,
    make_forward_nodes,
    send_forward,
)
from ..sources.bilibili import download_b_file, extra_bili_info, merge_file_to_mp4
from ..state import is_content_enabled
from .runtime import (
    BILI_SESSDATA,
    BILIBILI_PROXY,
    GLOBAL_NICKNAME,
)
from .video import (
    VIDEO_DURATION_MAXIMUM,
    _gather_downloads,
)

try:
    from bilibili_api import Credential, article, live, request_settings, video
    from bilibili_api.favorite_list import get_video_favorite_list_content
    from bilibili_api.opus import Opus
    from bilibili_api.video import VideoCodecs, VideoDownloadURLDataDetecter

    BILIBILI_AVAILABLE = True
except ImportError:
    article = live = video = Credential = None
    request_settings = None
    get_video_favorite_list_content = None
    Opus = VideoCodecs = VideoDownloadURLDataDetecter = None
    BILIBILI_AVAILABLE = False


def clean_bilibili_url(url: str) -> str:
    """清理 B 站视频链接，仅保留分 P 参数。"""
    bv_match = re.search(r"/video/(BV[1-9A-Za-z]{10})", url)

    if not bv_match:
        return url

    bvid = bv_match.group(1)

    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    # 只保留分P参数
    p = query.get("p", [None])[0]

    result = f"https://www.bilibili.com/video/{bvid}"

    if p:
        result += f"?p={p}"

    return result


if BILIBILI_AVAILABLE:
    request_settings.set_trust_env(False)
    request_settings.set_proxy(BILIBILI_PROXY or "")
    credential = Credential(sessdata=BILI_SESSDATA, proxy=BILIBILI_PROXY)
else:
    credential = None


@bili23.handle()
@resolve_handler
@resolve_controller
async def bilibili(bot: Bot, event: GroupMessageEvent) -> None:
    """
        哔哩哔哩解析
    :param bot:
    :param event:
    :return:
    """
    if not BILIBILI_AVAILABLE:
        await bili23.finish(
            "当前环境未安装 bilibili-api-python，暂时无法解析 B 站链接。"
        )

    # 消息
    url = get_resolver_message(event)
    # 正则匹配
    url_reg = (
        r"https?://(?:space|www|live|t)\.bilibili\.com/"
        r"[A-Za-z\d._?%&+\-=/#]*"
    )
    b_short_rex = r"https?://(?:b23\.tv|bili2233\.cn)/[A-Za-z\d._?%&+\-=/#]+"
    # BV处理；支持“解析 BV...”，也兼容只传 BV 号的旧调用方式。
    raw_bv_match = re.fullmatch(
        r"(?:解析|resolver)\s+(BV[1-9a-zA-Z]{10})", url, re.IGNORECASE
    )
    if raw_bv_match:
        url = "https://www.bilibili.com/video/" + raw_bv_match.group(1)
    elif re.match(r"^BV[1-9a-zA-Z]{10}$", url):
        url = "https://www.bilibili.com/video/" + url
    # 处理短号、小程序问题
    if "b23.tv" in url or "bili2233.cn" in url or "QQ小程序" in url:
        short_match = re.search(b_short_rex, url.replace("\\", ""))

        if not short_match:
            await bili23.finish("未识别到有效的 Bilibili 短链接。")

        b_short_url = short_match.group(0)

        try:
            async with httpx.AsyncClient(
                headers=BILIBILI_HEADER,
                follow_redirects=False,
                proxy=BILIBILI_PROXY,
                trust_env=False,
                timeout=10.0,
            ) as client:
                resp = await client.get(b_short_url)

            # B23 短链接正常情况下返回重定向
            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("location")

                if not location:
                    logger.warning(
                        f"[Bilibili] 短链接跳转响应缺少 Location：{b_short_url}"
                    )
                    return

                # 此处先只获取跳转地址
                url = location

                logger.debug(f"[Bilibili] 短链接解析：{b_short_url} -> {url}")

            else:
                resp.raise_for_status()
                url = str(resp.url)

        except httpx.HTTPError as exc:
            logger.warning(f"[Bilibili] 短链接响应失败：{exc}")
            return

    # ==============================
    # 所有链接统一走这里
    # ==============================

    url = clean_bilibili_url(url)

    url_match = re.search(url_reg, url)

    if not url_match:
        await bili23.finish("未识别到有效的 Bilibili 链接。")

    url = url_match.group(0)
    # ===============发现解析的是动态，转移一下===============
    if ("t.bilibili.com" in url or "/opus" in url) and BILI_SESSDATA != "":
        # 去除多余的参数
        if "?" in url:
            url = url[: url.index("?")]
        dynamic_id = int(url.rstrip("/").split("/")[-1].split("?")[0])
        dynamic_info = await Opus(dynamic_id, credential).get_info()
        # 这里比较复杂，暂时不用管，使用下面这个算法即可实现哔哩哔哩动态转发
        if dynamic_info is not None:
            title = dynamic_info["item"]["basic"]["title"]
            paragraphs = []
            for module in dynamic_info["item"]["modules"]:
                if "module_content" in module:
                    paragraphs = module["module_content"]["paragraphs"]
                    break
            desc = paragraphs[0]["text"]["nodes"][0]["word"]["words"]
            pics = paragraphs[1]["pic"]["pics"]
            dynamic_nodes = [
                Message(f"{GLOBAL_NICKNAME}识别：B站动态\n标题：{title}\n{desc}")
            ]
            dynamic_nodes.extend(MessageSegment.image(pic["url"]) for pic in pics)
            await send_forward(
                bot,
                event,
                make_forward_nodes(bot.self_id, dynamic_nodes),
            )
        return
    if "t.bilibili.com" in url or "/opus" in url:
        await bili23.finish("Bilibili 动态解析需要配置 BILI_SESSDATA。")
    # 直播间识别
    if "live" in url:
        # https://live.bilibili.com/30528999?hotRank=0
        room_match = re.search(r"/(\d+)(?:\?.*)?$", url)
        if not room_match:
            await bili23.finish("无法从 Bilibili 直播链接中提取房间号。")
        room_id = room_match.group(1)
        room = live.LiveRoom(
            room_display_id=int(room_id),
            credential=credential,
        )
        room_info = (await room.get_room_info())["room_info"]
        title, cover, keyframe = (
            room_info["title"],
            room_info["cover"],
            room_info["keyframe"],
        )
        await send_forward(
            bot,
            event,
            make_forward_nodes(
                bot.self_id,
                [
                    MessageSegment.image(cover),
                    MessageSegment.image(keyframe),
                    MessageSegment.text(
                        f"{GLOBAL_NICKNAME}识别：哔哩哔哩直播，{title}"
                    ),
                ],
            ),
        )
        return
    # 专栏识别
    if "read" in url:
        read_id = re.search(r"read\/cv(\d+)", url).group(1)
        ar = article.Article(read_id, credential=credential)
        # 如果专栏为公开笔记，则转换为笔记类
        # NOTE: 笔记类的函数与专栏类的函数基本一致
        if ar.is_note():
            ar = ar.turn_to_note()
        # 加载内容
        await ar.fetch_content()
        markdown_path = CACHE_DIR / "article.md"
        with markdown_path.open("w", encoding="utf-8") as f:
            f.write(ar.markdown())
        await send_forward(
            bot,
            event,
            make_forward_nodes(
                bot.self_id,
                [
                    MessageSegment.text(f"{GLOBAL_NICKNAME}识别：哔哩哔哩专栏"),
                    MessageSegment(type="file", data={"file": str(markdown_path)}),
                ],
            ),
        )
        return
    # 收藏夹识别
    if "favlist" in url and BILI_SESSDATA != "":
        # https://space.bilibili.com/22990202/favlist?fid=2344812202
        fav_id = re.search(r"favlist\?fid=(\d+)", url).group(1)
        fav_list = (
            await get_video_favorite_list_content(
                fav_id,
                credential=credential,
            )
        )["medias"][:10]
        favs = []
        for fav in fav_list:
            title, cover, intro, link = (
                fav["title"],
                fav["cover"],
                fav["intro"],
                fav["link"],
            )
            logger.info(title, cover, intro)
            favs.append(
                [
                    MessageSegment.image(cover),
                    MessageSegment.text(
                        f"🧉 标题：{title}\n📝 简介：{intro}\n🔗 链接：{link}"
                    ),
                ]
            )
        await send_forward(
            bot,
            event,
            make_forward_nodes(
                bot.self_id,
                [
                    MessageSegment.text(
                        f"{GLOBAL_NICKNAME}识别：哔哩哔哩收藏夹，正在为你找出相关链接请稍等..."
                    ),
                    *favs,
                ],
            ),
        )
        return
    if "favlist" in url:
        await bili23.finish("Bilibili 收藏夹解析需要配置 BILI_SESSDATA。")
    # 获取视频信息
    video_match = re.search(r"video/[^?\/ ]+", url)
    if not video_match:
        await bili23.finish("暂不支持此类 Bilibili 链接。")
    video_id = video_match.group(0).split("/")[1]
    v = video.Video(video_id, credential=credential)
    try:
        video_info = await v.get_info()
    except Exception as exc:
        logger.warning(f"[Bilibili] 获取视频信息响应失败：{exc}")
        return
    if video_info is None:
        logger.warning("[Bilibili] 获取视频信息响应为空")
        return
    video_title = video_info["title"]
    video_cover = video_info["pic"]
    video_desc = video_info["desc"]
    video_duration = video_info["duration"]
    # 校准 分p 的情况
    page_num = 0

    if video_info.get("pages"):
        pages = video_info["pages"]

        parsed_url = urlparse(url)

        if parsed_url.query:
            query_params = parse_qs(parsed_url.query)
            p_value = query_params.get("p", ["1"])[0]

            try:
                page_num = int(p_value) - 1
            except (TypeError, ValueError):
                page_num = 0

        page_num = max(0, min(page_num, len(pages) - 1))

        video_duration = pages[page_num].get(
            "duration",
            video_info.get("duration", 0),
        )
    video_duration = int(video_duration or 0)
    # 删除特殊字符
    video_title = clean_title(video_title)

    # B 站视频信息统一放进同一条合并转发：封面、标题/简介、数据。
    # 评论（如果开启）放在第 4 个节点，AI 总结放在评论之后；这里不再请求在线人数接口。
    send_id = get_target_id(event)
    bili_info_nodes: list[MessageSegment] = [
        MessageSegment.image(video_cover),
        MessageSegment.text(
            f"{GLOBAL_NICKNAME}识别：B站\n标题：{video_title}\n📝 简介：{video_desc}"
        ),
        MessageSegment.text(f"📊 数据\n{extra_bili_info(video_info)}"),
    ]

    # 评论模式为图片时，评论整体作为第 4 个节点；文字模式沿用原有的
    # 多节点评论格式，并把这些评论节点放到 AI 总结之前。
    comment_forward_nodes: list[MessageSegment] = []
    if is_content_enabled(send_id, "bilibili", "comment"):
        try:
            from ..comments import (
                format_bili_comments_to_nodes,
                get_bilibili_comments,
                render_bili_comments_image,
            )

            up_mid = video_info.get("owner", {}).get("mid")
            aid = video_info.get("aid")
            bvid = video_info.get("bvid")

            async with aiohttp.ClientSession(
                proxy=BILIBILI_PROXY,
                trust_env=False,
            ) as session:
                comments = await get_bilibili_comments(
                    session, aid, BILI_SESSDATA, bvid, up_mid
                )

            if comments:
                mode = comment_mode_map_in_memory.get(str(send_id), "image")
                if mode == "image":
                    try:
                        pic_bytes = await render_bili_comments_image(
                            comments, video_title
                        )
                        bili_info_nodes.append(MessageSegment.image(pic_bytes))
                    except Exception as img_err:
                        logger.error(
                            f"[Comment] B站图片渲染失败，自动降级为文字模式: {img_err}"
                        )
                        mode = "text"

                if mode == "text":
                    comment_forward_nodes = format_bili_comments_to_nodes(
                        bot.self_id,
                        comments,
                        video_title,
                        GLOBAL_NICKNAME,
                    )
        except Exception as c_err:
            logger.error(f"[Comment] 获取 B站评论失败，跳过评论节点: {c_err}")

    ai_summary = ""

    # 这里是总结内容，如果写了 cookie 就尝试获取；失败时不影响普通解析。
    if BILI_SESSDATA != "":
        try:
            ai_conclusion = await v.get_ai_conclusion(await v.get_cid(page_num))
            model_result = ai_conclusion.get("model_result") or {}
            ai_summary = (model_result.get("summary") or "").strip()
            if ai_summary:
                logger.info(
                    "[Bilibili] 已获取 AI 总结，将作为合并转发的最后一个节点发送"
                )
        except Exception as ai_exc:
            logger.warning(f"[Bilibili] 获取 AI 总结失败，跳过 AI 节点: {ai_exc}")

    bili_forward_nodes: list[MessageSegment] = list(
        make_forward_nodes(bot.self_id, bili_info_nodes)
    )
    if comment_forward_nodes:
        bili_forward_nodes.extend(comment_forward_nodes)
    if ai_summary:
        bili_forward_nodes.append(
            make_forward_nodes(
                bot.self_id, MessageSegment.text(f"AI总结\n{ai_summary}")
            )
        )

    await send_forward(
        bot,
        event,
        bili_forward_nodes,
    )

    if video_duration > VIDEO_DURATION_MAXIMUM:
        logger.warning(
            "[Bilibili] 视频时长超过限制，已跳过视频下载和发送："
            f"当前 {video_duration // 60} 分钟，"
            f"上限 {VIDEO_DURATION_MAXIMUM // 60} 分钟"
        )
        return

    # 获取下载链接
    logger.info(page_num)
    try:
        download_url_data = await v.get_download_url(page_index=page_num)
    except Exception as exc:
        logger.warning(f"[Bilibili] 获取视频流响应失败：{exc}")
        return
    transcode_video = False

    try:
        # 1. 尝试使用官方库的选择器
        detecter = VideoDownloadURLDataDetecter(download_url_data)
        streams = detecter.detect_best_streams(codecs=[VideoCodecs.AVC])
        if not streams or streams[0] is None:
            streams = detecter.detect_best_streams()
            if not streams or streams[0] is None:
                raise RuntimeError("没有可用的视频流")
            transcode_video = True
            logger.info("[Bilibili] 没有 AVC/H.264 视频流，将转码后发送")
        video_url = streams[0].url
        audio_url = (
            streams[1].url if len(streams) > 1 and streams[1] is not None else None
        )
    except Exception as e:
        # 2. 如果官方库因为编码枚举不匹配而崩溃，自动执行手动提取兜底
        logger.warning(
            f"[Bilibili] detect_best_streams 发生错误: {e}，正在启用手动提取流..."
        )
        try:
            # 兼容 DASH (分音视频) 格式
            dash_data = download_url_data.get("dash", {})
            video_list = dash_data.get("video", [])
            audio_list = dash_data.get("audio", [])

            avc_video = next(
                (
                    item
                    for item in video_list
                    if str(item.get("codecid")) == "7"
                    or str(item.get("codecs") or "").lower().startswith(("avc", "avc1"))
                ),
                None,
            )

            selected_video = avc_video or (video_list[0] if video_list else None)
            if selected_video:
                transcode_video = avc_video is None
                if transcode_video:
                    logger.info("[Bilibili] 备用视频流不是 AVC/H.264，将转码后发送")
                video_url = selected_video.get("baseUrl") or selected_video.get(
                    "base_url"
                )
                audio = audio_list[0] if audio_list else None
                audio_url = (
                    audio.get("baseUrl") or audio.get("base_url") if audio else None
                )
                if not video_url:
                    raise RuntimeError("视频流缺少下载地址")
            else:
                # 兼容非 DASH 的 DURL 格式
                durl_list = download_url_data.get("durl", [])
                if durl_list:
                    video_url = durl_list[0].get("url")
                    audio_url = None
                else:
                    raise Exception("未找到任何可用的视频流")
        except Exception as fallback_err:
            logger.error(f"[Bilibili] 备用流解析也宣告失败: {fallback_err}")
            return
    # 每次解析使用独立目录，避免同一视频被并发解析时互相覆盖。
    work_dir = Path(tempfile.mkdtemp(prefix=f"bili-{video_id}-", dir=CACHE_DIR))
    video_file = work_dir / "video.m4s"
    audio_file = work_dir / "audio.m4s"
    output_file = work_dir / "result.mp4"
    try:
        stream_urls = [video_url, *([audio_url] if audio_url else [])]
        await ensure_remote_total_within_limit(
            stream_urls,
            media_delivery.video_compress_limit,
            BILIBILI_PROXY,
            BILIBILI_HEADER,
        )
        budget = DownloadBudget(media_delivery.video_compress_limit)
        download_tasks = [
            download_b_file(
                video_url,
                video_file,
                logger.info,
                BILIBILI_PROXY,
                media_delivery.video_compress_limit,
                budget,
            ),
        ]
        if audio_url:
            download_tasks.append(
                download_b_file(
                    audio_url,
                    audio_file,
                    logger.info,
                    BILIBILI_PROXY,
                    media_delivery.video_compress_limit,
                    budget,
                )
            )
        await _gather_downloads(*download_tasks)
        await merge_file_to_mp4(
            str(video_file),
            str(audio_file) if audio_url else None,
            str(output_file),
            ffmpeg_path=madoka_config.ffmpeg_path,
            timeout=madoka_config.ffmpeg_timeout,
            transcode_video=transcode_video,
        )
        if await send_resolved_video(
            event,
            str(output_file),
            BILIBILI_PROXY,
        ):
            shutil.rmtree(work_dir, ignore_errors=True)
    except MediaSizeLimitExceeded as exc:
        logger.warning(f"[Bilibili] 视频超过大小限制，已跳过下载和发送：{exc}")
        return
    except ValueError as exc:
        await bili23.finish(f"视频无法下载：{exc}")
    except RuntimeError as exc:
        await bili23.finish(f"视频处理失败：{exc}")
