import re
from typing import Any, Dict

from nonebot.log import logger
from pyquery import PyQuery as Pq

from ..content import handle_bbcode, handle_html_tag
from ..images import handle_bbcode_img
from ..parser import HandlerRegistry
from ..subscription import Rss
from ..utils import get_summary


@HandlerRegistry.append_handler(parsing_type="summary", rex="(south|spring)-plus.net")
async def handle_summary(item: Dict[str, Any], tmp: str) -> str:
    rss_str = handle_bbcode(html=Pq(get_summary(item)))
    tmp += handle_html_tag(html=Pq(rss_str))
    return tmp


@HandlerRegistry.append_handler(parsing_type="picture", rex="(south|spring)-plus.net")
async def handle_picture(rss: Rss, item: Dict[str, Any], tmp: str) -> str:
    if rss.only_title:
        return ""

    res = ""
    try:
        res += await handle_bbcode_img(
            html=Pq(get_summary(item)),
            img_proxy=rss.img_proxy,
            img_num=rss.max_image_number,
            rss=rss,
        )
    except Exception as e:
        logger.warning(f"{rss.name} 没有正文内容！{e}")

    return f"{res}\n" if rss.only_pic else f"{tmp + res}\n"


@HandlerRegistry.append_handler(parsing_type="source", rex="(south|spring)-plus.net")
async def handle_source(item: Dict[str, Any]) -> str:
    source = item["link"]
    if re.search(r"^//", source):
        source = source.replace("//", "https://")
    return f"链接：{source}\n"
