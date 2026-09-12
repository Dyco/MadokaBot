import hashlib
from contextlib import suppress
from email.utils import parsedate_to_datetime
from io import BytesIO
from sqlite3 import Connection
from typing import Any, Dict, List, Optional, Tuple

import arrow
import imagehash
from nonebot.log import logger
from PIL import Image, UnidentifiedImageError
from pyquery import PyQuery as Pq
from tinydb import Query, TinyDB
from tinydb.operations import delete

from .config import config
from .images import download_image
from .subscription import Rss


def dict_hash(dictionary: Dict[str, Any]) -> str:
    """Build the stable identity used by the per-subscription cache."""
    identity = str(
        dictionary.get("guid")
        or dictionary.get("link")
        or f"{dictionary.get('title', '')}|{dictionary.get('published', '')}"
    )
    return hashlib.md5(identity.encode()).hexdigest()


def get_item_date(item: Dict[str, Any]) -> arrow.Arrow:
    if date := item.get("published") or item.get("updated"):
        with suppress(Exception):
            date = parsedate_to_datetime(date)
        return arrow.get(date)
    return arrow.now()


def check_update(db: TinyDB, new_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return unseen entries together with entries whose previous send failed."""
    pending_items: List[Dict[str, Any]] = db.search(Query().to_send.exists())
    if not new_items and not pending_items:
        return []

    old_hashes = {record.get("hash") for record in db.all()}
    for item in new_items:
        item_hash = dict_hash(item)
        if item_hash not in old_hashes:
            item["hash"] = item_hash
            pending_items.append(item)

    pending_items.sort(key=get_item_date)
    return pending_items


# 精简 xxx.json (缓存) 中的字段
def cache_filter(data: Dict[str, Any]) -> Dict[str, Any]:
    keys = [
        "guid",
        "link",
        "published",
        "updated",
        "title",
        "hash",
    ]
    if data.get("to_send"):
        keys += [
            "content",
            "summary",
            "to_send",
        ]
    return {k: v for k in keys if (v := data.get(k))}


# 对去重数据库进行管理
def cache_db_manage(conn: Connection) -> None:
    cursor = conn.cursor()
    try:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS main (
            "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
            "link" TEXT,
            "title" TEXT,
            "image_hash" TEXT,
            "datetime" TEXT DEFAULT (DATETIME('Now', 'LocalTime'))
        );
        """)
        cursor.execute(
            "DELETE FROM main WHERE datetime <= DATETIME('Now', 'LocalTime', ?);",
            (f"-{config.db_cache_expire} Day",),
        )
        conn.commit()
    finally:
        cursor.close()


# 对缓存 json 进行管理
def cache_json_manage(db: TinyDB, new_data_length: int) -> None:
    # 只保留最多 config.limit + new_data_length 条的记录
    limit = max(config.limit + new_data_length, 1)
    retains = db.all()
    retains.sort(key=get_item_date)
    retains = retains[-limit:]
    db.truncate()
    db.insert_multiple(retains)


async def get_image_hash(rss: Rss, summary: str, item: Dict[str, Any]) -> Optional[str]:
    try:
        summary_doc = Pq(summary)
    except Exception as e:
        logger.warning(e)
        # 没有正文内容直接跳过
        return None

    img_doc = summary_doc("img")
    # 只处理仅有一张图片的情况
    if len(img_doc) != 1:
        return None

    url = img_doc.attr("src")
    # 通过图像的指纹来判断是否实际是同一张图片
    content = await download_image(url, rss.img_proxy)

    if not content:
        return None

    try:
        im = Image.open(BytesIO(content))
    except UnidentifiedImageError:
        return None

    item["image_content"] = content
    # GIF 图片的 image_hash 实际上是第一帧的值，为了避免误伤直接跳过
    if im.format == "GIF":
        item["gif_url"] = url
        return None

    return str(imagehash.dhash(im))


# 去重判断
async def duplicate_exists(
    rss: Rss, conn: Connection, item: Dict[str, Any], summary: str
) -> Tuple[bool, Optional[str]]:
    link = item.get("link", "")
    title = item.get("title", "")
    image_hash = None
    cursor = conn.cursor()
    sql = "SELECT * FROM main WHERE"
    args = []

    conditions = []
    for mode in rss.duplicate_filter_mode:
        if mode == "image":
            image_hash = await get_image_hash(rss, summary, item)
            if image_hash:
                conditions.append("image_hash=?")
                args.append(image_hash)
        elif mode == "link":
            conditions.append("link=?")
            args.append(link)
        elif mode == "title":
            conditions.append("title=?")
            args.append(title)

    # An image-only rule cannot decide anything when the item has no usable
    # image fingerprint (for example an animated GIF).  Do not accidentally
    # turn that into ``WHERE 1=1`` and mark every such item as a duplicate.
    if not conditions:
        cursor.close()
        return False, image_hash

    joiner = " OR " if "or" in rss.duplicate_filter_mode else " AND "
    sql += f" ({joiner.join(conditions)})"

    try:
        cursor.execute(f"{sql};", args)
        result = cursor.fetchone()
        if result is None:
            return False, image_hash

        cursor.execute(
            "UPDATE main SET datetime = DATETIME('Now','LocalTime') WHERE id = ?;",
            (result[0],),
        )
        conn.commit()
        return True, image_hash
    finally:
        cursor.close()


# 消息发送后存入去重数据库
def insert_into_cache_db(
    conn: Connection, item: Dict[str, Any], image_hash: str
) -> None:
    cursor = conn.cursor()
    link = item.get("link", "")
    title = item.get("title", "")
    cursor.execute(
        "INSERT INTO main (link, title, image_hash) VALUES (?, ?, ?);",
        (link, title, image_hash),
    )
    cursor.close()
    conn.commit()


# 写入缓存 json
def write_item(db: TinyDB, new_item: Dict[str, Any]) -> None:
    if not new_item.get("to_send"):
        db.update(delete("to_send"), Query().hash == str(new_item.get("hash")))  # type: ignore
    db.upsert(cache_filter(new_item), Query().hash == str(new_item.get("hash")))
