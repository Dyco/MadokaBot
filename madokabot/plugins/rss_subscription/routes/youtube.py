from typing import Any, Dict

from ..images import handle_img_combo
from ..parser import HandlerRegistry
from ..subscription import Rss


@HandlerRegistry.append_handler(
    parsing_type="picture",
    rex=r"https:\/\/www\.youtube\.com\/feeds\/videos\.xml\?channel_id=",
)
async def handle_picture(rss: Rss, item: Dict[str, Any], tmp: str) -> str:
    if rss.only_title:
        return ""

    img_url = item["media_thumbnail"][0]["url"]
    res = await handle_img_combo(img_url, rss.img_proxy, rss)

    return f"{res}\n" if rss.only_pic else f"{tmp + res}\n"
