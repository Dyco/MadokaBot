"""各平台的链接解析处理器。"""

import asyncio
import json
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import aiohttp
import httpx

try:
    from bilibili_api import article, live, video, Credential
    from bilibili_api.favorite_list import get_video_favorite_list_content
    from bilibili_api.opus import Opus
    from bilibili_api.video import VideoCodecs, VideoDownloadURLDataDetecter

    BILIBILI_AVAILABLE = True
except ImportError:
    article = live = video = Credential = None
    get_video_favorite_list_content = None
    Opus = VideoCodecs = VideoDownloadURLDataDetecter = None
    BILIBILI_AVAILABLE = False

from nonebot import get_plugin_config, logger
from nonebot.adapters.onebot.v11 import (
    Bot,
    Event,
    Message,
    MessageSegment,
)
from nonebot.adapters.onebot.v11.event import GroupMessageEvent

from .config import Config
# noinspection PyUnresolvedReferences
from .constants import (
    BILIBILI_HEADER,
    COMMON_HEADER,
    DOUYIN_VIDEO,
    DY_TOUTIAO_INFO,
    GENERAL_REQ_LINK,
    KUGOU_TEMP_API,
    NETEASE_TEMP_API,
    NETEASE_TEMP_API_FALLBACK,
    URL_TYPE_CODE_DICT,
    WEIBO_SINGLE_INFO,
    XHS_REQ_LINK,
)
from .commands import (
    comment_mode_map as comment_mode_map_in_memory,
    comment_shutdown_list as comment_shutdown_list_in_memory,
    resolve_shutdown_list as resolve_shutdown_list_in_memory,
    resolve_controller,
    resolve_handler,
)
from .core.acfun import (
    download_m3u8_videos,
    merge_ac_file_to_mp4,
    parse_m3u8,
    parse_url,
)
from .core.bilibili import download_b_file, extra_bili_info, merge_file_to_mp4
from .core.downloads import (
    CACHE_DIR,
    DownloadBudget,
    clean_title,
    download_audio,
    download_image,
    download_video,
    ensure_remote_total_within_limit,
)
from .core.tiktok import dou_transfer_other, generate_x_bogus_url
from .core.weibo import mid2id
from .core.youtube import download_ytb_video, get_video_title
from .delivery import send_resolved_video
from .matchers import (
    acfun_matcher as acfun,
    bilibili_matcher as bili23,
    douyin_matcher as douyin,
    kugou_matcher as kg,
    netease_matcher as ncm,
    tiktok_matcher as tik,
    twitter_matcher as twit,
    weibo_matcher as weibo,
    xiaohongshu_matcher as xhs,
    youtube_matcher as y2b,
)
from .messages import (
    build_media_node,
    get_target_id,
    make_forward_nodes,
    send_forward,
    upload_file,
)

from ..madoka_bundle.config import config as madoka_config
from ..madoka_bundle.plugins.common import media_delivery


# 配置加载。解析器的独立代理为空时复用 MadokaBot 的全局 PROXY。
global_config = get_plugin_config(Config)
GLOBAL_NICKNAME = global_config.r_global_nickname.strip()
IS_OVERSEA = global_config.is_oversea
VIDEO_DURATION_MAXIMUM = global_config.video_duration_maximum
BILI_SESSDATA = global_config.bili_sessdata.strip()

resolver_proxy = global_config.resolver_proxy
if resolver_proxy:
    resolver_proxy = str(resolver_proxy).strip()
    if resolver_proxy and "://" not in resolver_proxy:
        resolver_proxy = f"http://{resolver_proxy}"
else:
    resolver_proxy = None

credential = Credential(sessdata=BILI_SESSDATA) if BILIBILI_AVAILABLE else None


async def _gather_downloads(*coroutines):
    """任一并发下载失败时，先取消并回收其余下载任务。"""
    tasks = [asyncio.create_task(coroutine) for coroutine in coroutines]
    try:
        return await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


@bili23.handle()
@resolve_handler
@resolve_controller
async def bilibili(bot: Bot, event: Event) -> None:
    """
        哔哩哔哩解析
    :param bot:
    :param event:
    :return:
    """
    if not BILIBILI_AVAILABLE:
        await bili23.finish("当前环境未安装 bilibili-api-python，暂时无法解析 B 站链接。")

    # 消息
    url: str = str(event.message).strip()
    # 正则匹配
    url_reg = (
        r"https?://(?:space|www|live|t)\.bilibili\.com/"
        r"[A-Za-z\d._?%&+\-=/#]*"
    )
    b_short_rex = (
        r"https?://(?:b23\.tv|bili2233\.cn)/[A-Za-z\d._?%&+\-=/#]+"
    )
    # BV处理；支持“解析 BV...”，也兼容只传 BV 号的旧调用方式。
    raw_bv_match = re.fullmatch(r"(?:解析|resolver)\s+(BV[1-9a-zA-Z]{10})", url, re.IGNORECASE)
    if raw_bv_match:
        url = 'https://www.bilibili.com/video/' + raw_bv_match.group(1)
    elif re.match(r'^BV[1-9a-zA-Z]{10}$', url):
        url = 'https://www.bilibili.com/video/' + url
    # 处理短号、小程序问题
    if "b23.tv" in url or "bili2233.cn" in url or "QQ小程序" in url:
        short_match = re.search(b_short_rex, url.replace("\\", ""))
        if not short_match:
            await bili23.finish("未识别到有效的 Bilibili 短链接。")
        b_short_url = short_match.group(0)
        resp = httpx.get(
            b_short_url,
            headers=BILIBILI_HEADER,
            follow_redirects=True,
            proxy=resolver_proxy,
            trust_env=False,
        )
        url: str = str(resp.url)
    else:
        url_match = re.search(url_reg, url)
        if not url_match:
            await bili23.finish("未识别到有效的 Bilibili 链接。")
        url = url_match.group(0)
    # ===============发现解析的是动态，转移一下===============
    if ('t.bilibili.com' in url or '/opus' in url) and BILI_SESSDATA != '':
        # 去除多余的参数
        if '?' in url:
            url = url[:url.index('?')]
        dynamic_id = int(url.rstrip("/").split("/")[-1].split("?")[0])
        dynamic_info = await Opus(dynamic_id, credential).get_info()
        # 这里比较复杂，暂时不用管，使用下面这个算法即可实现哔哩哔哩动态转发
        if dynamic_info is not None:
            title = dynamic_info['item']['basic']['title']
            paragraphs = []
            for module in dynamic_info['item']['modules']:
                if 'module_content' in module:
                    paragraphs = module['module_content']['paragraphs']
                    break
            desc = paragraphs[0]['text']['nodes'][0]['word']['words']
            pics = paragraphs[1]['pic']['pics']
            dynamic_nodes = [
                Message(f"{GLOBAL_NICKNAME}识别：B站动态\n标题：{title}\n{desc}")
            ]
            dynamic_nodes.extend(MessageSegment.image(pic['url']) for pic in pics)
            await send_forward(
                bot,
                event,
                make_forward_nodes(bot.self_id, dynamic_nodes),
            )
        return
    if 't.bilibili.com' in url or '/opus' in url:
        await bili23.finish("Bilibili 动态解析需要配置 BILI_SESSDATA。")
    # 直播间识别
    if 'live' in url:
        # https://live.bilibili.com/30528999?hotRank=0
        room_match = re.search(r"/(\d+)(?:\?.*)?$", url)
        if not room_match:
            await bili23.finish("无法从 Bilibili 直播链接中提取房间号。")
        room_id = room_match.group(1)
        room = live.LiveRoom(room_display_id=int(room_id))
        room_info = (await room.get_room_info())['room_info']
        title, cover, keyframe = room_info['title'], room_info['cover'], room_info['keyframe']
        await send_forward(
            bot,
            event,
            make_forward_nodes(
                bot.self_id,
                [
                    MessageSegment.image(cover),
                    MessageSegment.image(keyframe),
                    MessageSegment.text(f"{GLOBAL_NICKNAME}识别：哔哩哔哩直播，{title}"),
                ],
            ),
        )
        return
    # 专栏识别
    if 'read' in url:
        read_id = re.search(r'read\/cv(\d+)', url).group(1)
        ar = article.Article(read_id)
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
    if 'favlist' in url and BILI_SESSDATA != '':
        # https://space.bilibili.com/22990202/favlist?fid=2344812202
        fav_id = re.search(r'favlist\?fid=(\d+)', url).group(1)
        fav_list = (await get_video_favorite_list_content(fav_id))['medias'][:10]
        favs = []
        for fav in fav_list:
            title, cover, intro, link = fav['title'], fav['cover'], fav['intro'], fav['link']
            logger.info(title, cover, intro)
            favs.append(
                [MessageSegment.image(cover),
                 MessageSegment.text(f'🧉 标题：{title}\n📝 简介：{intro}\n🔗 链接：{link}')])
        await send_forward(
            bot,
            event,
            make_forward_nodes(
                bot.self_id,
                [
                    MessageSegment.text(
                        f'{GLOBAL_NICKNAME}识别：哔哩哔哩收藏夹，正在为你找出相关链接请稍等...'
                    ),
                    *favs,
                ],
            ),
        )
        return
    if 'favlist' in url:
        await bili23.finish("Bilibili 收藏夹解析需要配置 BILI_SESSDATA。")
    # 获取视频信息
    video_match = re.search(r"video/[^?\/ ]+", url)
    if not video_match:
        await bili23.finish("暂不支持此类 Bilibili 链接。")
    video_id = video_match.group(0).split('/')[1]
    v = video.Video(video_id, credential=credential)
    video_info = await v.get_info()
    if video_info is None:
        await send_forward(
            bot,
            event,
            make_forward_nodes(
                bot.self_id,
                MessageSegment.text(f"{GLOBAL_NICKNAME}识别：B站，出错，无法获取数据！"),
            ),
        )
        return
    video_title = video_info["title"]
    video_cover = video_info["pic"]
    video_desc = video_info["desc"]
    video_duration = video_info["duration"]
    # 校准 分p 的情况
    page_num = 0
    if video_info.get('pages'):
        # 解析URL
        parsed_url = urlparse(url)
        # 检查是否有查询字符串
        if parsed_url.query:
            # 解析查询字符串中的参数
            query_params = parse_qs(parsed_url.query)
            # 获取指定参数的值，如果参数不存在，则返回None
            page_num = int(query_params.get('p', [1])[0]) - 1
        else:
            page_num = 0
        pages = video_info['pages']
        page_num = max(0, min(page_num, len(pages) - 1))
        video_duration = pages[page_num].get(
            'duration',
            video_info.get('duration', 0),
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
            f"{GLOBAL_NICKNAME}识别：B站\n"
            f"标题：{video_title}\n"
            f"📝 简介：{video_desc}"
        ),
        MessageSegment.text(f"📊 数据\n{extra_bili_info(video_info)}"),
    ]

    if video_duration > VIDEO_DURATION_MAXIMUM:
        bili_info_nodes[-1] = MessageSegment.text(
            f"📊 数据\n{extra_bili_info(video_info)}\n"
            "---------\n"
            f"⚠️ 当前视频时长 {video_duration // 60} 分钟，超过管理员设置的最长时间 "
            f"{VIDEO_DURATION_MAXIMUM // 60} 分钟！"
        )
    # 评论模式为图片时，评论整体作为第 4 个节点；文字模式沿用原有的
    # 多节点评论格式，并把这些评论节点放到 AI 总结之前。
    comment_forward_nodes: list[MessageSegment] = []
    if send_id not in comment_shutdown_list_in_memory:
        try:
            from .core.comment import get_bilibili_comments, render_bili_comments_image, \
                format_bili_comments_to_nodes

            up_mid = video_info.get("owner", {}).get("mid")
            aid = video_info.get("aid")
            bvid = video_info.get("bvid")

            async with aiohttp.ClientSession() as session:
                comments = await get_bilibili_comments(session, aid, BILI_SESSDATA, bvid, up_mid)

            if comments:
                mode = comment_mode_map_in_memory.get(str(send_id), "image")
                if mode == "image":
                    try:
                        pic_bytes = await render_bili_comments_image(comments, video_title)
                        bili_info_nodes.append(MessageSegment.image(pic_bytes))
                    except Exception as img_err:
                        logger.error(f"[Comment] B站图片渲染失败，自动降级为文字模式: {img_err}")
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
                logger.info("[Bilibili] 已获取 AI 总结，将作为合并转发的最后一个节点发送")
        except Exception as ai_exc:
            logger.warning(f"[Bilibili] 获取 AI 总结失败，跳过 AI 节点: {ai_exc}")

    bili_forward_nodes: list[MessageSegment] = list(
        make_forward_nodes(bot.self_id, bili_info_nodes)
    )
    if comment_forward_nodes:
        bili_forward_nodes.extend(comment_forward_nodes)
    if ai_summary:
        bili_forward_nodes.append(
            make_forward_nodes(bot.self_id, MessageSegment.text(f"AI总结\n{ai_summary}"))
        )

    await send_forward(
        bot,
        event,
        bili_forward_nodes,
    )
    if video_duration > VIDEO_DURATION_MAXIMUM:
        return
    # 获取下载链接
    logger.info(page_num)
    download_url_data = await v.get_download_url(page_index=page_num)
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
            streams[1].url
            if len(streams) > 1 and streams[1] is not None
            else None
        )
    except Exception as e:
        # 2. 如果官方库因为编码枚举不匹配而崩溃，自动执行手动提取兜底
        logger.warning(f"[Bilibili] detect_best_streams 发生错误: {e}，正在启用手动提取流...")
        try:
            # 兼容 DASH (分音视频) 格式
            dash_data = download_url_data.get('dash', {})
            video_list = dash_data.get('video', [])
            audio_list = dash_data.get('audio', [])

            avc_video = next(
                (
                    item
                    for item in video_list
                    if str(item.get("codecid")) == "7"
                    or str(item.get("codecs") or "").lower().startswith(
                        ("avc", "avc1")
                    )
                ),
                None,
            )

            selected_video = avc_video or (video_list[0] if video_list else None)
            if selected_video:
                transcode_video = avc_video is None
                if transcode_video:
                    logger.info("[Bilibili] 备用视频流不是 AVC/H.264，将转码后发送")
                video_url = selected_video.get('baseUrl') or selected_video.get('base_url')
                audio = audio_list[0] if audio_list else None
                audio_url = (
                    audio.get('baseUrl') or audio.get('base_url')
                    if audio
                    else None
                )
                if not video_url:
                    raise RuntimeError("视频流缺少下载地址")
            else:
                # 兼容非 DASH 的 DURL 格式
                durl_list = download_url_data.get('durl', [])
                if durl_list:
                    video_url = durl_list[0].get('url')
                    audio_url = None
                else:
                    raise Exception("未找到任何可用的视频流")
        except Exception as fallback_err:
            logger.error(f"[Bilibili] 备用流解析也宣告失败: {fallback_err}")
            await bili23.finish("解析失败：B站流媒体接口发生不兼容的变更。")
            return
    # 每次解析使用独立目录，避免同一视频被并发解析时互相覆盖。
    with tempfile.TemporaryDirectory(
        prefix=f"bili-{video_id}-",
        dir=CACHE_DIR,
    ) as temp_dir:
        work_dir = Path(temp_dir)
        video_file = work_dir / "video.m4s"
        audio_file = work_dir / "audio.m4s"
        output_file = work_dir / "result.mp4"
        try:
            stream_urls = [video_url, *([audio_url] if audio_url else [])]
            await ensure_remote_total_within_limit(
                stream_urls,
                media_delivery.video_compress_limit,
                resolver_proxy,
                BILIBILI_HEADER,
            )
            budget = DownloadBudget(media_delivery.video_compress_limit)
            download_tasks = [
                download_b_file(
                    video_url,
                    video_file,
                    logger.info,
                    resolver_proxy,
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
                        resolver_proxy,
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
            await send_resolved_video(event, str(output_file))
        except ValueError as exc:
            await bili23.finish(f"视频无法下载：{exc}")
        except RuntimeError as exc:
            await bili23.finish(f"视频处理失败：{exc}")


@douyin.handle()
@resolve_handler
@resolve_controller
async def dy(bot: Bot, event: Event) -> None:
    """
        抖音解析
    :param bot:
    :param event:
    :return:
    """
    # 消息
    msg: str = str(event.message).strip()
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
            proxy=resolver_proxy,
        )
        dou_url_2 = str(response.url)
    except httpx.HTTPError as exc:
        logger.error(f"抖音短链展开失败: {exc}")
        await douyin.finish("抖音链接展开失败，请稍后重试。")

    # 实况图集临时解决方案，eg.  https://v.douyin.com/iDsVgJKL/
    if "share/slides" in dou_url_2:
        cover, author, title, images = await dou_transfer_other(dou_url)
        # 如果第一个不为None 大概率是成功
        if author is not None:
            slide_segments = [
                Message([MessageSegment.image(cover), MessageSegment.text(
                    f"{GLOBAL_NICKNAME}识别：【抖音】\n作者：{author}\n标题：{title}"
                )]),
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
                MessageSegment.text(f"{GLOBAL_NICKNAME}识别：抖音，无法获取到管理员设置的抖音ck！"),
            ),
        )
        return
    # API、一些后续要用到的参数
    headers = {
                  'Accept-Language': 'zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2',
                  'referer': f'https://www.douyin.com/video/{dou_id}',
                  'cookie': douyin_ck
              } | COMMON_HEADER
    api_url = DOUYIN_VIDEO.replace("{}", dou_id)
    try:
        api_url = generate_x_bogus_url(api_url, headers)
    except RuntimeError as exc:
        logger.error(str(exc))
        await douyin.finish(str(exc))
    async with aiohttp.ClientSession() as session:
        async with session.get(api_url, headers=headers, timeout=10) as response:
            detail = await response.json()
            if detail is None:
                await send_forward(
                    bot,
                    event,
                    make_forward_nodes(
                        bot.self_id,
                        MessageSegment.text(f"{GLOBAL_NICKNAME}识别：抖音，解析失败！"),
                    ),
                )
                return
            # 获取信息
            detail = detail['aweme_detail']
            desc = detail.get('desc', '')
            # 判断是图片还是视频
            url_type_code = detail['aweme_type']
            url_type = URL_TYPE_CODE_DICT.get(url_type_code, 'video')

            # 抖音的说明、图片和评论统一放进同一条合并转发。
            info_segment = MessageSegment.text(
                f"{GLOBAL_NICKNAME}识别：抖音\n{detail.get('desc')}"
            )
            comment_segment: MessageSegment | None = None
            comment_forward_nodes: list[MessageSegment] = []
            send_id = get_target_id(event)
            if (
                send_id not in comment_shutdown_list_in_memory
                and send_id not in resolve_shutdown_list_in_memory
            ):
                try:
                    from .core.comment import (
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
                                    desc or ("抖音图集" if url_type == "image" else "抖音视频"),
                                )
                                comment_segment = MessageSegment.image(comment_bytes)
                            except Exception as img_err:
                                logger.error(f"[Comment] 抖音图片渲染失败，自动降级为文字模式: {img_err}")
                                mode = "text"

                        if mode == "text":
                            comment_forward_nodes = format_comments_to_nodes(
                                bot.self_id,
                                comments,
                                desc or ("抖音图集" if url_type == "image" else "抖音视频"),
                                GLOBAL_NICKNAME,
                            )
                except Exception as c_err:
                    logger.error(f"[Comment] 获取抖音评论失败，跳过评论节点: {c_err}")

            # 根据类型进行发送
            if url_type == 'video':
                forward_nodes = list(make_forward_nodes(bot.self_id, [info_segment]))
                if comment_segment is not None:
                    forward_nodes.append(make_forward_nodes(bot.self_id, comment_segment))
                forward_nodes.extend(comment_forward_nodes)
                await send_forward(bot, event, forward_nodes)

                # 识别播放地址
                player_uri = detail.get("video").get("play_addr")['uri']
                player_real_addr = DY_TOUTIAO_INFO.replace("{}", player_uri)
                # 发送视频
                # logger.info(player_addr)
                # await douyin.send(Message(MessageSegment.video(player_addr)))
                await send_resolved_video(event, player_real_addr)
            elif url_type == 'image':
                # 无水印图片列表/No watermark image list
                no_watermark_image_list = []
                # 有水印图片列表/With watermark image list
                watermark_image_list = []
                # 遍历图片列表/Traverse image list
                for i in detail['images']:
                    # 无水印图片列表
                    # no_watermark_image_list.append(i['url_list'][0])
                    no_watermark_image_list.append(MessageSegment.image(i['url_list'][0]))
                    # 有水印图片列表
                    # watermark_image_list.append(i['download_url_list'][0])
                forward_segments = [info_segment, *no_watermark_image_list]
                if comment_segment is not None:
                    forward_segments.append(comment_segment)
                forward_nodes = list(make_forward_nodes(bot.self_id, forward_segments))
                forward_nodes.extend(comment_forward_nodes)
                await send_forward(bot, event, forward_nodes)


@tik.handle()
@resolve_handler
@resolve_controller
async def tiktok(bot: Bot, event: Event) -> None:
    """
        tiktok解析
    :param bot:
    :param event:
    :return:
    """
    # 消息
    url: str = str(event.message).strip()

    # 海外服务器判断
    proxy = None if IS_OVERSEA else resolver_proxy

    url_reg = r"(http:|https:)\/\/www.tiktok.com\/[A-Za-z\d._?%&+\-=\/#@]*"
    url_short_reg = r"(http:|https:)\/\/vt.tiktok.com\/[A-Za-z\d._?%&+\-=\/#]*"
    url_short_reg2 = r"(http:|https:)\/\/vm.tiktok.com\/[A-Za-z\d._?%&+\-=\/#]*"

    if "vt.tiktok" in url:
        temp_url = re.search(url_short_reg, url)[0]
        temp_resp = httpx.get(temp_url, follow_redirects=True, proxy=proxy)
        url = str(temp_resp.url)
    elif "vm.tiktok" in url:
        temp_url = re.search(url_short_reg2, url)[0]
        temp_resp = httpx.get(
            temp_url,
            headers={"User-Agent": "facebookexternalhit/1.1"},
            follow_redirects=True,
            proxy=proxy,
        )
        url = str(temp_resp.url)
        # logger.info(url)
    else:
        url = re.search(url_reg, url)[0]
    try:
        title = await get_video_title(url, IS_OVERSEA, resolver_proxy, "tiktok")
        target_tik_video_path = await download_ytb_video(
            url,
            IS_OVERSEA,
            CACHE_DIR,
            resolver_proxy,
            "tiktok",
            media_delivery.video_compress_limit,
        )
    except RuntimeError as exc:
        await tik.finish(str(exc))

    await send_forward(
        bot,
        event,
        make_forward_nodes(
            bot.self_id,
            MessageSegment.text(f"{GLOBAL_NICKNAME}识别：TikTok\n标题：{title}"),
        ),
    )

    await send_resolved_video(event, target_tik_video_path)


@acfun.handle()
@resolve_handler
@resolve_controller
async def ac(bot: Bot, event: Event) -> None:
    """
        acfun解析
    :param bot:
    :param event:
    :return:
    """
    # 消息
    inputMsg: str = str(event.message).strip()

    # 短号处理
    if "m.acfun.cn" in inputMsg:
        inputMsg = f"https://www.acfun.cn/v/ac{re.search(r'ac=([^&?]*)', inputMsg)[1]}"
    else:
        acfun_match = re.search(r"https?://[^\s]+acfun\.cn/[^\s]+", inputMsg, re.IGNORECASE)
        if acfun_match:
            inputMsg = acfun_match.group(0)

    url_m3u8s, video_name = parse_url(inputMsg, resolver_proxy)
    await send_forward(
        bot,
        event,
        make_forward_nodes(
            bot.self_id,
            MessageSegment.text(f"{GLOBAL_NICKNAME}识别：猴山\n标题：{video_name}"),
        ),
    )
    m3u8_full_urls, ts_names, _, output_file_name = parse_m3u8(
        url_m3u8s,
        resolver_proxy,
    )
    # logger.info(output_folder_name, output_file_name)
    try:
        await ensure_remote_total_within_limit(
            m3u8_full_urls,
            media_delivery.video_compress_limit,
            resolver_proxy,
        )
        budget = DownloadBudget(media_delivery.video_compress_limit)
        with tempfile.TemporaryDirectory(
            prefix="acfun-",
            dir=CACHE_DIR,
        ) as temp_dir:
            work_dir = Path(temp_dir)
            await _gather_downloads(
                *[
                    download_m3u8_videos(
                        url,
                        i,
                        work_dir,
                        resolver_proxy,
                        budget,
                    )
                    for i, url in enumerate(m3u8_full_urls)
                ]
            )
            output_path = await merge_ac_file_to_mp4(
                ts_names,
                output_file_name,
                work_dir=work_dir,
                ffmpeg_path=madoka_config.ffmpeg_path,
                timeout=madoka_config.ffmpeg_timeout,
            )
            await send_resolved_video(event, output_path)
    except ValueError as exc:
        await acfun.finish(f"视频无法下载：{exc}")
    except RuntimeError as exc:
        await acfun.finish(f"视频处理失败：{exc}")


@twit.handle()
@resolve_handler
@resolve_controller
async def twitter(bot: Bot, event: Event) -> None:
    """
        X解析
    :param bot:
    :param event:
    :return:
    """
    msg: str = str(event.message).strip()
    url_match = re.search(
        r"https?:\/\/x.com\/[0-9-a-zA-Z_]{1,20}\/status\/([0-9]+)",
        msg,
    )
    if not url_match:
        await twit.finish("未识别到有效的 X 帖子链接。")
    x_url = url_match.group(0)

    x_url = GENERAL_REQ_LINK.replace("{}", x_url)

    request_headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8,"
        "application/signed-exchange;v=b3;q=0.7",
        "Accept-Encoding": "gzip, deflate",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Host": "47.99.158.118",
        "Proxy-Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-User": "?1",
        **COMMON_HEADER,
    }
    try:
        async with httpx.AsyncClient(
            headers=request_headers,
            proxy=resolver_proxy,
            timeout=20,
            trust_env=False,
        ) as client:
            response = await client.get(x_url)
            response.raise_for_status()
            x_data: object = response.json().get("data")
            if x_data is None:
                photo_url = f"{x_url}/photo/1"
                logger.info(photo_url)
                response = await client.get(photo_url)
                response.raise_for_status()
                x_data = response.json().get("data")
    except (httpx.HTTPError, ValueError, AttributeError) as exc:
        logger.warning(f"X 链接解析接口请求失败：{exc}")
        await twit.finish("X 链接解析失败，请稍后重试。")

    if not isinstance(x_data, dict) or not x_data.get("url"):
        await twit.finish("X 链接解析失败，接口没有返回媒体地址。")
    x_url_res = str(x_data["url"])

    # 海外服务器判断
    proxy = None if IS_OVERSEA else resolver_proxy

    info_node = make_forward_nodes(
        bot.self_id,
        MessageSegment.text(f"{GLOBAL_NICKNAME}识别：小蓝鸟学习版"),
    )

    if Path(urlparse(x_url_res).path).suffix.lower() in {".jpg", ".jpeg", ".png"}:
        res = await download_image(x_url_res, "", proxy)
        try:
            media_node = build_media_node(int(bot.self_id), res)
            if media_node is None:
                await twit.finish("X 媒体格式暂不支持。")
            await send_forward(bot, event, [info_node, media_node])
        finally:
            Path(res).unlink(missing_ok=True)
        return

    # 视频交给统一媒体服务判断直发、压缩或拒绝。
    try:
        res = await download_video(
            x_url_res,
            proxy,
            max_size=media_delivery.video_compress_limit,
        )
    except ValueError as exc:
        await twit.finish(f"视频无法下载：{exc}")
    if not res:
        await twit.finish("X 视频下载失败，请稍后重试。")
    try:
        await send_forward(bot, event, info_node)
        await send_resolved_video(event, res)
    finally:
        Path(res).unlink(missing_ok=True)


@xhs.handle()
@resolve_handler
@resolve_controller
async def xiaohongshu(bot: Bot, event: Event):
    """
        小红书解析
    :param event:
    :return:
    """
    message_text = str(event.message).replace("&amp;", "&").strip()
    url_match = re.search(
        r"https?://(?:xhslink|(?:www\.)?xiaohongshu)\.com/"
        r"[A-Za-z\d._?%&+\-=/#@]*",
        message_text,
    )
    if not url_match:
        await xhs.finish("未识别到有效的小红书链接。")
    msg_url = url_match.group(0)
    # 如果没有设置xhs的ck就结束，因为获取不到
    xhs_ck = getattr(global_config, "xhs_ck", "")
    if xhs_ck == "":
        logger.error(global_config)
        await send_forward(
            bot,
            event,
            make_forward_nodes(
                bot.self_id,
                MessageSegment.text(
                    f"{GLOBAL_NICKNAME}识别内容来自：【小红书】\n无法获取到管理员设置的小红书ck！"
                ),
            ),
        )
        return
    # 请求头
    headers = {
        "accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/webp,image/apng,*/*;q=0.8,"
            "application/signed-exchange;v=b3;q=0.9"
        ),
        "cookie": xhs_ck,
    } | COMMON_HEADER
    if "xhslink" in msg_url:
        msg_url = httpx.get(
            msg_url,
            headers=headers,
            follow_redirects=True,
            proxy=resolver_proxy,
            timeout=20,
            trust_env=False,
        ).url
        msg_url = str(msg_url)
    xhs_id = re.search(r'/explore/(\w+)', msg_url)
    if not xhs_id:
        xhs_id = re.search(r'/discovery/item/(\w+)', msg_url)
    if not xhs_id:
        xhs_id = re.search(r'source=note&noteId=(\w+)', msg_url)
    if not xhs_id:
        await xhs.finish("无法从小红书链接中提取笔记 ID。")
    xhs_id = xhs_id.group(1)
    # 解析 URL 参数
    parsed_url = urlparse(msg_url)
    params = parse_qs(parsed_url.query)
    # 提取 xsec_source 和 xsec_token
    xsec_source = params.get('xsec_source', [None])[0] or "pc_feed"
    xsec_token = params.get('xsec_token', [None])[0]

    html = httpx.get(
        f"{XHS_REQ_LINK}{xhs_id}?xsec_source={xsec_source}&xsec_token={xsec_token}",
        headers=headers,
        proxy=resolver_proxy,
        timeout=20,
        trust_env=False,
    ).text
    # response_json = re.findall('window.__INITIAL_STATE__=(.*?)</script>', html)[0]
    try:
        response_json = re.findall('window.__INITIAL_STATE__=(.*?)</script>', html)[0]
    except IndexError:
        await send_forward(
            bot,
            event,
            make_forward_nodes(
                bot.self_id,
                MessageSegment.text(
                    f"{GLOBAL_NICKNAME}识别内容来自：【小红书】\n当前ck已失效，请联系管理员重新设置的小红书ck！"
                ),
            ),
        )
        return
    response_json = response_json.replace("undefined", "null")
    response_json = json.loads(response_json)
    note_data = response_json['note']['noteDetailMap'][xhs_id]['note']
    type = note_data['type']
    note_title = note_data['title']
    note_desc = note_data['desc']
    xhs_info_node = make_forward_nodes(
        bot.self_id,
        MessageSegment.text(
            f"{GLOBAL_NICKNAME}识别：小红书\n标题：{note_title}\n{note_desc}"
        ),
    )

    aio_task = []
    if type == 'normal':
        image_list = note_data['imageList']
        # 批量下载
        async with aiohttp.ClientSession() as session:
            for index, item in enumerate(image_list):
                aio_task.append(asyncio.create_task(
                    download_image(
                        item["urlDefault"],
                        str(CACHE_DIR / f"{index}.jpg"),
                        proxy=resolver_proxy,
                        session=session,
                    )
                )
                )
            links_path = await asyncio.gather(*aio_task)
    elif type == 'video':
        # 这是一条解析有水印的视频
        logger.info(note_data['video'])

        video_url = note_data['video']['media']['stream']['h264'][0]['masterUrl']

        # ⚠️ 废弃，解析无水印视频video.consumer.originVideoKey
        # video_url = f"http://sns-video-bd.xhscdn.com/{note_data['video']['consumer']['originVideoKey']}"
        await send_forward(bot, event, xhs_info_node)
        try:
            path = await download_video(
                video_url,
                resolver_proxy,
                max_size=media_delivery.video_compress_limit,
            )
        except ValueError as exc:
            await xhs.finish(f"视频无法下载：{exc}")
        # await xhs.send(Message(MessageSegment.video(path)))
        await send_resolved_video(event, path)
        return
    else:
        await xhs.finish(f"暂不支持的小红书内容类型：{type}")

    # 说明和图片统一放进同一条合并转发。
    xhs_forward_nodes = [xhs_info_node]
    xhs_forward_nodes.extend(
        make_forward_nodes(
            bot.self_id,
            [
                MessageSegment.image(file=Path(link).resolve().as_uri())
                for link in links_path
            ],
        )
    )
    await send_forward(bot, event, xhs_forward_nodes)
    # 清除图片
    for temp in links_path:
        Path(temp).unlink(missing_ok=True)


@y2b.handle()
@resolve_handler
@resolve_controller
async def youtube(bot: Bot, event: Event):
    msg_url = re.search(
        r"(?:https?://)?(?:www\.)?youtube\.com/[A-Za-z\d._?%&+\-=/#]*"
        r"|(?:https?://)?youtu\.be/[A-Za-z\d._?%&+\-=/#]*",
        str(event.message).strip(),
    )[0]

    # 海外服务器判断
    proxy = None if IS_OVERSEA else resolver_proxy

    try:
        title = await get_video_title(msg_url, IS_OVERSEA, proxy)
        target_ytb_video_path = await download_ytb_video(
            msg_url,
            IS_OVERSEA,
            CACHE_DIR,
            proxy,
            max_size=media_delivery.video_compress_limit,
        )
    except RuntimeError as exc:
        await y2b.finish(str(exc))

    await send_forward(
        bot,
        event,
        make_forward_nodes(
            bot.self_id,
            MessageSegment.text(f"{GLOBAL_NICKNAME}识别：油管\n标题：{title}"),
        ),
    )

    await send_resolved_video(event, target_ytb_video_path)


@ncm.handle()
@resolve_handler
@resolve_controller
async def netease(bot: Bot, event: Event):
    message = str(event.message)
    # 识别短链接
    if "163cn.tv" in message:
        try:
            short_url = re.search(r"(http:|https:)\/\/163cn\.tv\/([a-zA-Z0-9]+)", message).group(0)
            async with httpx.AsyncClient(
                proxy=resolver_proxy,
                timeout=20,
                trust_env=False,
            ) as client:
                head_resp = await client.head(short_url, follow_redirects=True)
            message = str(head_resp.url)
        except Exception as e:
            logger.error(f"[NCM] 短链解析失败: {e}")
            await ncm.finish(Message(f"❌ {GLOBAL_NICKNAME}无法解析此网易云短链接。"))

    match = re.search(r"id=(\d+)", message)
    if not match:
        await ncm.finish(Message(f"❌ {GLOBAL_NICKNAME}未能在链接中找到歌曲 ID。"))

    ncm_id = match.group(1)
    logger.info(f"[NCM] 歌曲 ID: {ncm_id}")

    api_candidates = [
        ("main", NETEASE_TEMP_API.replace('{}', ncm_id)),
        ("fallback", NETEASE_TEMP_API_FALLBACK.replace('{}', ncm_id)),
    ]

    ncm_url = None
    ncm_cover = None
    ncm_singer = '未知歌手'
    ncm_title = f'网易云歌曲_{ncm_id}'
    last_error = None

    for api_name, api_url in api_candidates:
        try:
            async with httpx.AsyncClient(
                proxy=resolver_proxy,
                timeout=15,
                trust_env=False,
            ) as client:
                response = await client.get(api_url, headers=COMMON_HEADER)
            logger.debug(f"[NCM][{api_name}] 接口状态: {response.status_code} | 内容: {response.text}")

            if response.status_code != 200:
                last_error = f"HTTP {response.status_code}"
                logger.warning(f"[NCM][{api_name}] 接口状态异常: {response.status_code}")
                continue

            resp_json = response.json()

            if api_name == "main":
                if resp_json.get('code') != 0:
                    last_error = resp_json.get('message', '未知错误')
                    logger.warning(f"[NCM][{api_name}] 接口返回错误: {last_error}")
                    continue

                data_list = resp_json.get('data')
                if not isinstance(data_list, list) or not data_list:
                    last_error = '接口未返回有效歌曲数据'
                    logger.warning(f"[NCM][{api_name}] 接口未返回有效 data: {resp_json}")
                    continue

                song_data = data_list[0]
                singers = song_data.get('singers') or []
                singer_names = [
                    singer.get('name') for singer in singers
                    if isinstance(singer, dict) and singer.get('name')
                ]

                ncm_url = song_data.get('url')
                ncm_cover = song_data.get('picurl')
                ncm_singer = ' / '.join(singer_names) if singer_names else '未知歌手'
                ncm_title = song_data.get('name') or f'网易云歌曲_{ncm_id}'
            else:
                if resp_json.get('status') != 200:
                    last_error = resp_json.get('msg', '未知错误')
                    logger.warning(f"[NCM][{api_name}] 接口返回错误: {last_error}")
                    continue

                ncm_url = resp_json.get('url')
                ncm_cover = resp_json.get('pic')
                ncm_singer = resp_json.get('ar_name') or '未知歌手'
                ncm_title = resp_json.get('name') or f'网易云歌曲_{ncm_id}'

            if ncm_url:
                logger.info(f"[NCM] 使用 {api_name} 接口解析成功")
                break

            last_error = '未获取到播放链接'
            logger.warning(f"[NCM][{api_name}] 接口未返回播放链接: {resp_json}")
        except Exception as e:
            last_error = str(e)
            logger.error(f"[NCM][{api_name}] 接口请求失败: {e}")

    if not ncm_url:
        await ncm.finish(f"❌ 未获取到播放链接，主备接口均失败：{last_error or '未知错误'}")
        return

    ncm_music_path = None
    try:
        ncm_music_path = await download_audio(ncm_url, resolver_proxy)
        ncm_forward_nodes = list(
            make_forward_nodes(
                bot.self_id,
                [
                    MessageSegment.image(ncm_cover),
                    MessageSegment.text(
                        f'{GLOBAL_NICKNAME}识别：网易云音乐\n'
                        f'歌名：{ncm_title} - {ncm_singer}'
                    ),
                    MessageSegment.record(ncm_music_path),
                ],
            )
        )
        await send_forward(bot, event, ncm_forward_nodes)
        await upload_file(
            bot, event, ncm_music_path,
            f'{ncm_title}-{ncm_singer}.{ncm_music_path.split(".")[-1]}',
        )
    except Exception as e:
        logger.error(f"[NCM] 音频下载/发送失败: {e}")
        await send_forward(
            bot,
            event,
            make_forward_nodes(bot.self_id, MessageSegment.text("❌ 音频下载或发送失败。")),
        )
    finally:
        if ncm_music_path and os.path.exists(ncm_music_path):
            os.unlink(ncm_music_path)


@kg.handle()
@resolve_handler
@resolve_controller
async def kugou(bot: Bot, event: Event):
    message = str(event.message)
    # logger.info(message)
    reg1 = r"https?://.*?kugou\.com.*?(?=\s|$|\n)"
    reg2 = r'jumpUrl":\s*"(https?:\\/\\/[^"]+)"'
    reg3 = r'jumpUrl":\s*"(https?://[^"]+)"'
    # 处理卡片问题
    if 'com.tencent.structmsg' in message:
        match = re.search(reg2, message)
        if match:
            get_url = match.group(1)
        else:
            match = re.search(reg3, message)
            if match:
                get_url = match.group(1)
            else:
                await send_forward(
                    bot,
                    event,
                    make_forward_nodes(
                        bot.self_id,
                        MessageSegment.text(f"{GLOBAL_NICKNAME}\n来源：【酷狗音乐】\n获取链接失败"),
                    ),
                )
                get_url = None
                return
        if get_url:
            url = json.loads('"' + get_url + '"')
    else:
        match = re.search(reg1, message)
        url = match.group()

        # 使用 httpx 获取 URL 的标题
    response = httpx.get(
        url,
        follow_redirects=True,
        proxy=resolver_proxy,
        timeout=20,
        trust_env=False,
    )
    if response.status_code == 200:
        title = response.text
        get_name = r"<title>(.*?)_高音质在线试听"
        name = re.search(get_name, title)
        if name:
            kugou_title = name.group(1)  # 只输出歌曲名和歌手名的部分
            kugou_vip_data = httpx.get(
                KUGOU_TEMP_API.replace("{}", kugou_title),
                headers=COMMON_HEADER,
                proxy=resolver_proxy,
                timeout=20,
                trust_env=False,
            ).json()
            # logger.info(kugou_vip_data)
            kugou_url = kugou_vip_data.get('music_url')
            kugou_cover = kugou_vip_data.get('cover')
            kugou_name = kugou_vip_data.get('title')
            kugou_singer = kugou_vip_data.get('singer')
            # 下载音频文件后会返回一个下载路径
            kugou_music_path = None
            try:
                kugou_music_path = await download_audio(kugou_url, resolver_proxy)
                kugou_forward_nodes = list(
                    make_forward_nodes(
                        bot.self_id,
                        [
                            MessageSegment.image(kugou_cover),
                            MessageSegment.text(
                                f'{GLOBAL_NICKNAME}识别：酷狗音乐\n'
                                f'歌曲：{kugou_name}-{kugou_singer}'
                            ),
                            MessageSegment.record(kugou_music_path),
                        ],
                    )
                )
                await send_forward(bot, event, kugou_forward_nodes)
                await upload_file(
                    bot,
                    event,
                    kugou_music_path,
                    f'{kugou_name}-{kugou_singer}.{kugou_music_path.split(".")[-1]}',
                )
            except Exception as exc:
                logger.error(f"[Kugou] 音频下载/发送失败: {exc}")
                await send_forward(
                    bot,
                    event,
                    make_forward_nodes(bot.self_id, MessageSegment.text("❌ 音频下载或发送失败。")),
                )
            finally:
                if kugou_music_path and os.path.exists(kugou_music_path):
                    os.unlink(kugou_music_path)
        else:
            await send_forward(
                bot,
                event,
                make_forward_nodes(
                    bot.self_id,
                    MessageSegment.text(
                        f"{GLOBAL_NICKNAME}\n来源：【酷狗音乐】\n不支持当前外链，请重新分享再试"
                    ),
                ),
            )
    else:
        await send_forward(
            bot,
            event,
            make_forward_nodes(
                bot.self_id,
                MessageSegment.text(f"{GLOBAL_NICKNAME}\n来源：【酷狗音乐】\n获取链接失败"),
            ),
        )


@weibo.handle()
@resolve_handler
@resolve_controller
async def wb(bot: Bot, event: Event):
    message = str(event.message)
    weibo_id = None
    reg = r'(jumpUrl|qqdocurl)": ?"(.*?)"'

    # 处理卡片问题
    if 'com.tencent.structmsg' in message or 'com.tencent.miniapp' in message:
        match = re.search(reg, message)
        logger.debug(f"微博卡片链接匹配结果: {match}")
        if match:
            get_url = match.group(2)
            logger.debug(f"微博卡片展开链接: {get_url}")
            if get_url:
                message = json.loads('"' + get_url + '"')
    # logger.info(message)
    # 判断是否包含 "m.weibo.cn"
    if "m.weibo.cn" in message:
        # https://m.weibo.cn/detail/4976424138313924
        match = re.search(r"(?<=detail/)[A-Za-z\d]+", message) or re.search(
            r"(?<=m.weibo.cn/)[A-Za-z\d]+/[A-Za-z\d]+",
            message,
        )
        weibo_id = match.group(0) if match else None

    # 判断是否包含 "weibo.com/tv/show" 且包含 "mid="
    elif "weibo.com/tv/show" in message and "mid=" in message:
        # https://weibo.com/tv/show/1034:5007449447661594?mid=5007452630158934
        match = re.search(r'(?<=mid=)[A-Za-z\d]+', message)
        if match:
            weibo_id = mid2id(match.group(0))

    # 判断是否包含 "weibo.com"
    elif "weibo.com" in message:
        # https://weibo.com/1707895270/5006106478773472
        match = re.search(r'(?<=weibo.com/)[A-Za-z\d]+/[A-Za-z\d]+', message)
        weibo_id = match.group(0) if match else None

    # 无法获取到id则返回失败信息
    if not weibo_id:
        await weibo.finish(Message("解析失败：无法获取到wb的id"))
    # 最终获取到的 id
    weibo_id = weibo_id.split("/")[1] if "/" in weibo_id else weibo_id
    logger.info(weibo_id)
    # 请求数据
    headers = {
        "accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,image/apng,*/*;q=0.8,"
            "application/signed-exchange;v=b3;q=0.9"
        ),
        "cookie": (
            "_T_WM=40835919903; WEIBOCN_FROM=1110006030; "
            "MLOGIN=0; XSRF-TOKEN=4399c8"
        ),
        "Referer": f"https://m.weibo.cn/detail/{weibo_id}",
    } | COMMON_HEADER
    resp = httpx.get(
        WEIBO_SINGLE_INFO.format(weibo_id),
        headers=headers,
        proxy=resolver_proxy,
        timeout=20,
        trust_env=False,
    ).json()
    weibo_data = resp['data']
    logger.info(weibo_data)
    text, status_title, source, region_name, pics, page_info = (
        weibo_data.get(key)
        for key in [
            "text",
            "status_title",
            "source",
            "region_name",
            "pics",
            "page_info",
        ]
    )
    # 微博说明和图片统一放进同一条合并转发；视频本体仍走统一的视频发送流程。
    weibo_forward_nodes = [
        make_forward_nodes(
            bot.self_id,
            MessageSegment.text(
                f"{GLOBAL_NICKNAME}识别：微博\n"
                f"{re.sub(r'<[^>]+>', '', text or '')}\n"
                f"{status_title or ''}\n{source or ''}\t{region_name or ''}"
            ),
        )
    ]
    links_path = []
    if pics:
        pic_urls = [item["url"] for item in pics]
        image_headers = {"Referer": "http://blog.sina.com.cn/"} | COMMON_HEADER
        download_image_funcs = [
            asyncio.create_task(
                download_image(
                    item,
                    "",
                    resolver_proxy,
                    headers=image_headers,
                )
            )
            for item in pic_urls
        ]
        links_path = await asyncio.gather(*download_image_funcs)
        weibo_forward_nodes.extend(
            make_forward_nodes(
                bot.self_id,
                [
                    MessageSegment.image(file=Path(link).resolve().as_uri())
                    for link in links_path
                ],
            )
        )
    await send_forward(bot, event, weibo_forward_nodes)
    # 清除图片
    for temp in links_path:
        Path(temp).unlink(missing_ok=True)
    if isinstance(page_info, dict):
        urls = page_info.get("urls") or {}
        video_url = urls.get("mp4_720p_mp4", "") or urls.get("mp4_hd_mp4", "")
        if video_url:
            video_headers = {
                "accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "image/avif,image/webp,image/apng,*/*;q=0.8,"
                    "application/signed-exchange;v=b3;q=0.9"
                ),
                "referer": "https://weibo.com/",
            }
            try:
                path = await download_video(
                    video_url,
                    resolver_proxy,
                    ext_headers=video_headers,
                    max_size=media_delivery.video_compress_limit,
                )
            except ValueError as exc:
                await weibo.finish(f"视频无法下载：{exc}")
            await send_resolved_video(event, path)
