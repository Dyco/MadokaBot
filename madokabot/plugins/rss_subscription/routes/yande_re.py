import asyncio
import re
from typing import Any, Dict, Iterable, Tuple

import aiohttp
from nonebot.log import logger

from ..cache import check_update, write_item
from ..parser import HandlerRegistry
from ..subscription import Rss
from ..utils import get_proxy


YANDERE_API_URL = "https://yande.re/post.json"
YANDERE_POST_ID_PATTERN = re.compile(r"/post/show/(\d+)")
_request_lock = asyncio.Lock()
_last_request_at = 0.0


def _tag_type_matches(tag_type: Any, expected: str) -> bool:
    if isinstance(tag_type, str):
        normalized = tag_type.strip().lower()
        if expected == "character":
            return normalized in {"4", "character", "characters", "角色"}
        return normalized in {"3", "copyright", "作品", "series"}
    if isinstance(tag_type, int):
        return tag_type == (4 if expected == "character" else 3)
    return False


def _format_tags(value: Any) -> str:
    if isinstance(value, str):
        values = value.split()
    elif isinstance(value, (list, tuple, set)):
        values = [
            str(tag.get("name") or tag.get("tag") or tag.get("term") or "")
            if isinstance(tag, dict)
            else str(tag)
            for tag in value
        ]
    else:
        values = []
    return "、".join(
        dict.fromkeys(
            tag.replace("_", " ").strip() for tag in values if tag.strip()
        )
    )


def _tag_fields(post: Dict[str, Any]) -> Tuple[str, str]:
    character_tags = _format_tags(
        post.get("tag_string_character") or post.get("character_tags")
    )
    copyright_tags = _format_tags(
        post.get("tag_string_copyright") or post.get("copyright_tags")
    )
    if character_tags or copyright_tags:
        return character_tags, copyright_tags

    tags = post.get("tags")
    typed_tags: Iterable[Tuple[Any, Any]] = ()
    if isinstance(tags, dict):
        typed_tags = tags.items()
    elif isinstance(tags, list):
        typed_tags = (
            (
                tag.get("name") or tag.get("tag") or tag.get("term"),
                tag.get("type") or tag.get("label") or tag.get("category"),
            )
            for tag in tags
            if isinstance(tag, dict)
        )

    characters = []
    copyrights = []
    for tag_name, tag_type in typed_tags:
        if not tag_name:
            continue
        if _tag_type_matches(tag_type, "character"):
            characters.append(str(tag_name))
        elif _tag_type_matches(tag_type, "copyright"):
            copyrights.append(str(tag_name))

    return _format_tags(characters), _format_tags(copyrights)


async def _fetch_post_tags(
    session: aiohttp.ClientSession, post_id: str
) -> Tuple[str, str]:
    global _last_request_at

    async with _request_lock:
        loop = asyncio.get_running_loop()
        wait_time = 1.0 - (loop.time() - _last_request_at)
        if wait_time > 0:
            await asyncio.sleep(wait_time)

        try:
            async with session.get(
                YANDERE_API_URL,
                params={
                    "api_version": 2,
                    "tags": f"id:{post_id}",
                    "include_tags": 1,
                },
                proxy=get_proxy(),
            ) as response:
                response.raise_for_status()
                payload = await response.json(content_type=None)
        finally:
            _last_request_at = loop.time()

    if isinstance(payload, list):
        payload = payload[0] if payload else {}
    if not isinstance(payload, dict):
        return "", ""
    if isinstance(payload.get("post"), dict):
        payload = payload["post"]
    return _tag_fields(payload)


# 检查更新
@HandlerRegistry.append_before_handler(rex=r"https\:\/\/yande\.re\/post\/piclens\?tags\=")
async def load_updates(rss: Rss, state: Dict[str, Any]) -> Dict[str, Any]:
    db = state["tinydb"]
    change_data = check_update(db, state["new_data"])
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=10),
        headers={"User-Agent": "MadokaBot-RSS/1.0"},
    ) as session:
        for item in change_data.copy():
            if item.get("media_content"):
                item["summary"] = re.sub(
                    r'https://[^"]+',
                    item["media_content"][0]["url"],
                    item.get("summary", ""),
                )

            character_tags, copyright_tags = _tag_fields(item)
            post_id = YANDERE_POST_ID_PATTERN.search(str(item.get("link") or ""))
            tag_fetch_failed = False
            if not (character_tags or copyright_tags) and post_id:
                try:
                    character_tags, copyright_tags = await _fetch_post_tags(
                        session, post_id.group(1)
                    )
                except Exception as exc:
                    tag_fetch_failed = True
                    logger.warning(
                        f"{rss.name} 获取 Yande.re 标签失败[{post_id.group(1)}]：{exc}"
                    )

            item["imageboard_character"] = character_tags
            item["imageboard_copyright"] = copyright_tags
            if not (character_tags or copyright_tags):
                post_reference = post_id.group(1) if post_id else item.get("link", "")
                logger.info(
                    f"{rss.name} 条目[{post_reference}]缺少角色/作品标签，跳过推送"
                )
                if not tag_fetch_failed:
                    write_item(db, item)
                change_data.remove(item)
    return {"change_data": change_data}
