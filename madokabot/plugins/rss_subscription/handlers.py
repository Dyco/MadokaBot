import re
import sqlite3
from difflib import SequenceMatcher
from importlib import import_module
from typing import Any, Dict, List

import arrow
import emoji
from nonebot.log import logger
from pyquery import PyQuery as Pq

from .cache import (
    cache_db_manage,
    cache_json_manage,
    check_update,
    duplicate_exists,
    get_item_date,
    write_item,
)
from .config import CACHE_DB_PATH, config
from .content import handle_html_tag
from .delivery import handle_send_msgs
from .download import download_torrents
from .images import handle_img
from .parser import HandlerRegistry
from .routes import ROUTE_MODULES
from .subscription import Rss
from .utils import get_proxy, get_summary

for module in ROUTE_MODULES:
    import_module(f".routes.{module}", package=__package__)


@HandlerRegistry.append_before_handler()
async def load_updates(state: Dict[str, Any]) -> Dict[str, Any]:
    db = state.get("tinydb")
    change_data = check_update(db, state.get("new_data"))
    return {"change_data": change_data}


@HandlerRegistry.append_before_handler(priority=11)  # type: ignore
async def filter_entries(rss: Rss, state: Dict[str, Any]) -> Dict[str, Any]:
    change_data = state.get("change_data")
    db = state.get("tinydb")
    for item in change_data.copy():
        summary = get_summary(item)
        if config.black_word and re.findall("|".join(config.black_word), summary):
            logger.info("内含屏蔽词，已经取消推送该消息")
            write_item(db, item)
            change_data.remove(item)
            continue
        # down_torrent_keyword实际表示关键词白名单。
        if rss.down_torrent_keyword and not re.search(
            rss.down_torrent_keyword, summary
        ):
            write_item(db, item)
            change_data.remove(item)
            continue
        if rss.black_keyword and (
            re.search(rss.black_keyword, item["title"])
            or re.search(rss.black_keyword, summary)
        ):
            write_item(db, item)
            change_data.remove(item)
            continue
        if (rss.only_pic or rss.only_has_pic) and not re.search(
            r"<img[^>]+>|<video\b|\[img]|\[CQ:(?:image|video)\b",
            summary,
            flags=re.IGNORECASE,
        ):
            media_content = []
            for field in ("media_content", "enclosures", "links"):
                values = item.get(field) or []
                if not isinstance(values, (list, tuple)):
                    values = [values]
                media_content.extend(values)
            has_video_enclosure = any(
                isinstance(media, dict)
                and (
                    str(media.get("type") or "").lower().startswith("video/")
                    or str(media.get("medium") or "").lower() == "video"
                    or re.search(
                        r"\.(?:mp4|m4v|mov|mkv|webm|avi|flv|mpeg|mpg|wmv|ts)(?:[?#]|$)",
                        str(media.get("url") or media.get("href") or ""),
                        flags=re.IGNORECASE,
                    )
                )
                for media in media_content
            )
            if has_video_enclosure:
                continue
            logger.info(f"{rss.name} 已开启仅媒体，该消息没有图片或视频，将跳过")
            write_item(db, item)
            change_data.remove(item)

    return {"change_data": change_data}


@HandlerRegistry.append_before_handler(priority=12)  # type: ignore
async def filter_duplicates(rss: Rss, state: Dict[str, Any]) -> Dict[str, Any]:
    change_data = state.get("change_data")
    conn = state.get("conn")
    db = state.get("tinydb")

    if not rss.duplicate_filter_mode:
        return {"change_data": change_data}

    if not conn:
        conn = sqlite3.connect(str(CACHE_DB_PATH))
        conn.set_trace_callback(logger.debug)

    cache_db_manage(conn)

    delete = []
    for index, item in enumerate(change_data):
        is_duplicate, image_hash = await duplicate_exists(
            rss=rss,
            conn=conn,
            item=item,
            summary=get_summary(item),
        )
        if is_duplicate:
            write_item(db, item)
            delete.append(index)
        else:
            change_data[index]["image_hash"] = str(image_hash)

    change_data = [
        item for index, item in enumerate(change_data) if index not in delete
    ]

    return {
        "change_data": change_data,
        "conn": conn,
    }


@HandlerRegistry.append_handler(parsing_type="title")
async def handle_title(rss: Rss, item: Dict[str, Any]) -> str:
    if rss.only_pic:
        return ""

    title = item["title"]

    if not config.blockquote:
        title = re.sub(r" - 转发 .*", "", title)

    res = f"标题：{title}\n"
    if not rss.only_title:
        res += "\n"
    if rss.only_title:
        return emoji.emojize(res, language="alias")

    try:
        summary_html = Pq(get_summary(item))
        if not config.blockquote:
            summary_html.remove("blockquote")
        similarity = SequenceMatcher(None, summary_html.text()[: len(title)], title)
        if similarity.ratio() > 0.6:
            res = ""
    except Exception as e:
        logger.warning(f"{rss.name} 没有正文内容！{e}")

    return emoji.emojize(res, language="alias")


@HandlerRegistry.append_handler(parsing_type="summary", priority=1)
async def skip_summary_if_only_title_or_picture(
    rss: Rss, tmp_state: Dict[str, Any]
) -> str:
    """仅推送标题或图片时跳过正文处理。"""
    if rss.only_title or rss.only_pic:
        tmp_state["continue"] = False
    return ""


@HandlerRegistry.append_handler(parsing_type="summary")  # type: ignore
async def handle_summary(rss: Rss, item: Dict[str, Any], tmp: str) -> str:
    try:
        tmp += handle_html_tag(html=Pq(get_summary(item)))
    except Exception as e:
        logger.warning(f"{rss.name} 没有正文内容！{e}")
    return tmp


@HandlerRegistry.append_handler(parsing_type="summary", priority=11)  # type: ignore
async def remove_summary_content(rss: Rss, tmp: str) -> str:
    """移除订阅配置指定的正文内容并整理空行。"""
    if rss.content_to_remove:
        for pattern in rss.content_to_remove:
            tmp = re.sub(pattern, "", tmp)
        while "\n\n\n" in tmp:
            tmp = tmp.replace("\n\n\n", "\n\n")
        tmp = tmp.strip()
    return emoji.emojize(tmp, language="alias")


@HandlerRegistry.append_handler(parsing_type="picture")
async def handle_picture(rss: Rss, item: Dict[str, Any], tmp: str) -> str:
    if rss.only_title:
        return ""

    res = ""
    try:
        res += await handle_img(
            item=item,
            img_proxy=rss.img_proxy,
            img_num=rss.max_image_number,
            rss=rss,
        )
    except Exception as e:
        logger.warning(f"{rss.name} 没有正文内容！{e}")

    return f"{res}\n" if rss.only_pic else f"{tmp + res}\n"


@HandlerRegistry.append_handler(parsing_type="source")
async def handle_source(item: Dict[str, Any]) -> str:
    return f"链接：{item['link']}\n"


@HandlerRegistry.append_handler(parsing_type="torrent")
async def handle_torrent(rss: Rss, item: Dict[str, Any]) -> str:
    res: List[str] = []
    if rss.down_torrent:
        try:
            download_infos = await download_torrents(
                rss=rss, item=item, proxy=get_proxy(rss.img_proxy)
            )
            if download_infos:
                res.append("\naria2 下载任务已添加：")
                res.extend(
                    [
                        f"{info.get('summary', info.get('name', '未知文件'))}"
                        for info in download_infos
                    ]
                )
        except Exception:
            logger.exception("aria2 下载种子时出错")
    return "\n".join(res)


@HandlerRegistry.append_handler(parsing_type="date")
async def handle_date(item: Dict[str, Any]) -> str:
    date = get_item_date(item)
    date = date.replace(tzinfo="local") if date > arrow.now() else date.to("local")
    return f"日期：{date.format('YYYY年MM月DD日 HH:mm:ss')}"


@HandlerRegistry.append_handler(parsing_type="after")
async def handle_message(
    rss: Rss,
    state: Dict[str, Any],
    item: Dict[str, Any],
    item_msg: str,
) -> str:
    if config.rss_auto_forward or rss.send_forward_msg:
        return ""

    await handle_send_msgs(rss=rss, messages=[item_msg], items=[item], state=state)
    return ""


@HandlerRegistry.append_after_handler()
async def after_handler(rss: Rss, state: Dict[str, Any]) -> Dict[str, Any]:
    if (config.rss_auto_forward or rss.send_forward_msg) and state["messages"]:
        await handle_send_msgs(
            rss=rss, messages=state["messages"], items=state["items"], state=state
        )

    if not state["is_last_batch"]:
        return {}

    db = state["tinydb"]
    new_data_length = len(state["new_data"])
    cache_json_manage(db, new_data_length)

    message_count = len(state["change_data"])
    success_count = message_count - state["error_count"]

    if success_count > 0:
        logger.info(f"{rss.name} 新消息推送完毕，共计：{success_count}/{message_count}")
    elif message_count > 0:
        logger.error(f"{rss.name} 新消息推送失败，共计：{message_count}")
    else:
        logger.info(f"{rss.name} 没有新信息")

    if conn := state["conn"]:
        conn.close()

    db.close()

    return {}
