import asyncio
import base64
import random
import re
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple, Union
from urllib.parse import urljoin

import aiohttp
from nonebot.log import logger
from PIL import Image, UnidentifiedImageError
from pyquery import PyQuery as Pq
from tenacity import RetryError, retry, stop_after_attempt, stop_after_delay
from yarl import URL

from ..madoka_bundle.plugins.common import MediaSizeLimitExceeded, media_delivery
from ..madoka_bundle.plugins.common.media import VIDEO_SEND_CACHE_DIR
from .config import DATA_PATH, config
from .subscription import Rss
from .utils import get_proxy, get_summary


VIDEO_SUFFIXES = frozenset(
    {
        ".mp4",
        ".m4v",
        ".mov",
        ".mkv",
        ".webm",
        ".avi",
        ".flv",
        ".mpeg",
        ".mpg",
        ".wmv",
        ".ts",
    }
)
VIDEO_CONTENT_TYPES = {
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/quicktime": ".mov",
    "video/x-matroska": ".mkv",
    "video/mpeg": ".mpeg",
    "video/x-msvideo": ".avi",
}


# 通过 ezgif 压缩 GIF
@retry(stop=(stop_after_attempt(5) | stop_after_delay(30)))
async def resize_gif(url: str, resize_ratio: int = 2) -> Optional[bytes]:
    async with aiohttp.ClientSession() as session:
        resp = await session.post(
            "https://s3.ezgif.com/resize",
            data={"new-image-url": url},
            proxy=get_proxy(),
        )
        d = Pq(await resp.text())
        next_url = d("form").attr("action")
        _file = d("form > input[type=hidden]:nth-child(1)").attr("value")
        token = d("form > input[type=hidden]:nth-child(2)").attr("value")
        old_width = d("form > input[type=hidden]:nth-child(3)").attr("value")
        old_height = d("form > input[type=hidden]:nth-child(4)").attr("value")
        data = {
            "file": _file,
            "token": token,
            "old_width": old_width,
            "old_height": old_height,
            "width": str(int(old_width) // resize_ratio),
            "method": "gifsicle",
            "ar": "force",
        }
        resp = await session.post(
            next_url, params="ajax=true", data=data, proxy=get_proxy()
        )
        d = Pq(await resp.text())
        output_img_url = "https:" + d("img:nth-child(1)").attr("src")
        return await download_image(output_img_url, bool(get_proxy()))


# 通过 ezgif 把视频中间 4 秒转 GIF 作为预览
@retry(stop=(stop_after_attempt(5) | stop_after_delay(30)))
async def get_preview_gif_from_video(url: str) -> str:
    async with aiohttp.ClientSession() as session:
        resp = await session.post(
            "https://s3.ezgif.com/video-to-gif",
            data={"new-image-url": url},
            proxy=get_proxy(),
        )
        d = Pq(await resp.text())
        video_length = re.search(
            r"\d\d:\d\d:\d\d", str(d("#main > p.filestats > strong"))
        ).group()  # type: ignore
        hours = int(video_length.split(":")[0])
        minutes = int(video_length.split(":")[1])
        seconds = int(video_length.split(":")[2])
        video_length_median = (hours * 60 * 60 + minutes * 60 + seconds) // 2
        next_url = d("form").attr("action")
        _file = d("form > input[type=hidden]:nth-child(1)").attr("value")
        token = d("form > input[type=hidden]:nth-child(2)").attr("value")
        default_end = d("#end").attr("value")
        if float(default_end) >= 4:
            start = video_length_median - 2
            end = video_length_median + 2
        else:
            start = 0
            end = default_end
        data = {
            "file": _file,
            "token": token,
            "start": start,
            "end": end,
            "size": 320,
            "fps": 25,
            "method": "ffmpeg",
        }
        resp = await session.post(
            next_url, params="ajax=true", data=data, proxy=get_proxy()
        )
        d = Pq(await resp.text())
        return f'https:{d("img:nth-child(1)").attr("src")}'


# 图片压缩
async def zip_pic(url: str, content: bytes) -> Union[Image.Image, bytes, None]:
    # 打开一个 JPEG/PNG/GIF/WEBP 图像文件
    try:
        im = Image.open(BytesIO(content))
    except UnidentifiedImageError:
        logger.error(f"无法识别图像文件 链接：[{url}]")
        return None
    if im.format != "GIF":
        # 先把 WEBP 图像转为 PNG
        if im.format == "WEBP":
            im = im.convert("RGBA")
        # 对图像文件进行缩小处理
        im.thumbnail((config.zip_size, config.zip_size))
        if im.mode not in {"RGB", "RGBA"}:
            im = im.convert("RGBA")
        width, height = im.size
        logger.debug(f"Resize image to: {width} x {height}")
        # 和谐
        points = [(0, 0), (0, height - 1), (width - 1, 0), (width - 1, height - 1)]
        for x, y in points:
            im.putpixel((x, y), random.randint(0, 255))
        return im
    else:
        if len(content) > config.gif_zip_size * 1024:
            try:
                return await resize_gif(url)
            except RetryError:
                logger.error(f"GIF 图片[{url}]压缩失败，将发送原图")
        return content


# 将图片转化为 base64
def get_pic_base64(content: Union[Image.Image, bytes, None]) -> str:
    if not content:
        return ""
    if isinstance(content, Image.Image):
        with BytesIO() as output:
            content.save(output, format=content.format or "PNG")
            content = output.getvalue()
    if isinstance(content, bytes):
        return str(base64.b64encode(content).decode())
    return ""


# 去你的 pixiv.cat
async def resolve_pixiv_cat_url(url: str) -> str:
    img_id = re.sub("https://pixiv.cat/", "", url)
    img_id = img_id[:-4]
    info_list = img_id.split("-")
    async with aiohttp.ClientSession() as session:
        try:
            resp = await session.get(
                f"https://api.obfs.dev/api/pixiv/illust?id={info_list[0]}",
                proxy=get_proxy(),
            )
            resp_json = await resp.json()
            if len(info_list) >= 2:
                return str(
                    resp_json["illust"]["meta_pages"][int(info_list[1]) - 1][
                        "image_urls"
                    ]["original"]
                )
            else:
                return str(
                    resp_json["illust"]["meta_single_page"]["original_image_url"]
                )
        except Exception as e:
            logger.error(f"处理pixiv.cat链接时出现问题 ：{e} 链接：[{url}]")
            return url


@retry(stop=(stop_after_attempt(5) | stop_after_delay(30)))
async def download_image_detail(
    url: str,
    proxy: bool,
    headers: Optional[Mapping[str, str]] = None,
) -> Optional[bytes]:
    async with aiohttp.ClientSession(raise_for_status=True) as session:
        referer = f"{URL(url).scheme}://{URL(url).host}/"
        request_headers = {"referer": referer}
        if headers:
            request_headers.update(headers)
        try:
            resp = await session.get(
                url, headers=request_headers, proxy=get_proxy(open_proxy=proxy)
            )
            content = await resp.read()
            # 如果图片无法获取到，直接返回
            if len(content) == 0:
                if "pixiv.cat" in url:
                    url = await resolve_pixiv_cat_url(url=url)
                    return await download_image(url, proxy, headers)
                logger.error(
                    f"图片[{url}]下载失败！ Content-Type: {resp.headers.get('Content-Type')} status: {resp.status}"
                )
                return None
            # 如果图片格式为 SVG ，先转换为 PNG
            if resp.headers.get("Content-Type", "").startswith("image/svg+xml"):
                next_url = str(
                    URL("https://images.weserv.nl/").with_query(f"url={url}&output=png")
                )
                return await download_image(next_url, proxy, headers)
            return content
        except Exception as e:
            logger.warning(f"图片[{url}]下载失败！将重试最多 5 次！\n{e}")
            raise


async def download_image(
    url: str,
    proxy: bool = False,
    headers: Optional[Mapping[str, str]] = None,
) -> Optional[bytes]:
    try:
        return await download_image_detail(url=url, proxy=proxy, headers=headers)
    except RetryError:
        logger.error(f"图片[{url}]下载失败！已达最大重试次数！有可能需要开启代理！")
        return None


async def handle_img_combo(
    url: str,
    img_proxy: bool,
    rss: Optional[Rss] = None,
    headers: Optional[Mapping[str, str]] = None,
) -> str:
    """'
    下载图片并返回可用的CQ码

    参数:
        url: 需要下载的图片地址
        img_proxy: 是否使用代理下载图片
        rss: Rss对象
    返回值:
        返回当前图片的CQ码,以base64格式编码发送
        如获取图片失败将会提示图片走丢了
    """
    if content := await download_image(url, img_proxy, headers):
        if rss is not None and rss.download_pic:
            _url = URL(url)
            logger.debug(f"正在保存图片: {url}")
            try:
                save_image(content=content, file_url=_url, rss=rss)
            except Exception as e:
                logger.warning(f"在保存图片到本地时出现错误\nE:{repr(e)}")
        if resize_content := await zip_pic(url, content):
            if img_base64 := get_pic_base64(resize_content):
                return f"[CQ:image,file=base64://{img_base64}]"
    return f"\n图片走丢啦 链接：[{url}]\n"


async def handle_img_combo_with_content(
    url: str, content: bytes, rss: Optional[Rss] = None
) -> str:
    if rss is not None and rss.download_pic and url:
        try:
            save_image(content=content, file_url=URL(url), rss=rss)
        except Exception as e:
            logger.warning(f"在保存图片到本地时出现错误\nE:{repr(e)}")
    if resize_content := await zip_pic(url, content):
        if img_base64 := get_pic_base64(resize_content):
            return f"[CQ:image,file=base64://{img_base64}]"
    return f"\n图片走丢啦 链接：[{url}]\n" if url else "\n图片走丢啦\n"


def _get_media_url(value: Any) -> str:
    if isinstance(value, Mapping):
        value = value.get("url") or value.get("href") or value.get("src")
    return str(value or "").strip()


def _is_video_reference(url: str, media_type: str = "") -> bool:
    normalized_type = media_type.split(";", 1)[0].strip().lower()
    if normalized_type.startswith("video/"):
        return True
    return URL(url).path.lower().endswith(tuple(VIDEO_SUFFIXES))


def _video_urls(item: Dict[str, Any], html: Pq) -> list[str]:
    """从 HTML video/source 和常见 RSS 媒体字段中提取直链视频。"""
    urls: list[str] = []
    base_url = str(item.get("link") or "")

    def add_url(value: Any, media_type: str = "") -> None:
        url = _get_media_url(value)
        if not url:
            return
        url = urljoin(base_url, url)
        if _is_video_reference(url, media_type) and url not in urls:
            urls.append(url)

    for video in html("video").items():
        add_url(video.attr("src"), "video/*")
        for source in video("source").items():
            add_url(source.attr("src"), source.attr("type") or "video/*")

    for field in ("media_content", "enclosures"):
        values = item.get(field) or []
        if not isinstance(values, (list, tuple)):
            values = [values]
        for value in values:
            if isinstance(value, Mapping):
                media_type = str(value.get("type") or "")
                if str(value.get("medium") or "").lower() == "video":
                    media_type = media_type or "video/*"
            else:
                media_type = ""
            add_url(value, media_type)

    links = item.get("links") or []
    if isinstance(links, (list, tuple)):
        for value in links:
            if not isinstance(value, Mapping):
                continue
            relation = str(value.get("rel") or "").lower()
            media_type = str(value.get("type") or "")
            if str(value.get("medium") or "").lower() == "video":
                media_type = media_type or "video/*"
            if relation == "enclosure" or media_type.startswith("video/"):
                add_url(value, media_type)

    return urls


def _video_suffix(url: str, content_type: str) -> str:
    suffix = Path(URL(url).path).suffix.lower()
    if suffix in VIDEO_SUFFIXES:
        return suffix
    return VIDEO_CONTENT_TYPES.get(
        content_type.split(";", 1)[0].strip().lower(), ".mp4"
    )


async def download_video(
    url: str,
    img_proxy: bool,
    headers: Optional[Mapping[str, str]] = None,
) -> Optional[Path]:
    """流式下载直链视频，并在下载过程中执行统一大小限制。"""
    request_headers = {"referer": f"{URL(url).scheme}://{URL(url).host}/"}
    if headers:
        request_headers.update(headers)

    max_size = media_delivery.video_compress_limit
    path: Optional[Path] = None
    try:
        timeout = aiohttp.ClientTimeout(total=300)
        async with aiohttp.ClientSession(
            raise_for_status=True, timeout=timeout
        ) as session:
            async with session.get(
                url,
                headers=request_headers,
                proxy=get_proxy(open_proxy=img_proxy),
            ) as response:
                content_type = response.headers.get("Content-Type", "")
                content_length = response.headers.get("Content-Length")
                try:
                    expected_size = int(content_length or 0)
                except ValueError:
                    expected_size = 0
                if expected_size > max_size:
                    raise MediaSizeLimitExceeded(
                        f"视频大小 {expected_size / 1024 / 1024:.2f} MiB 超过上限 "
                        f"{max_size / 1024 / 1024:g} MiB"
                    )

                path = VIDEO_SEND_CACHE_DIR / (
                    f"rss-{uuid.uuid4().hex}{_video_suffix(url, content_type)}"
                )
                downloaded = 0
                with path.open("wb") as file:
                    async for chunk in response.content.iter_chunked(1024 * 1024):
                        downloaded += len(chunk)
                        if downloaded > max_size:
                            raise MediaSizeLimitExceeded(
                                f"视频下载大小超过上限 "
                                f"{max_size / 1024 / 1024:g} MiB"
                            )
                        await asyncio.to_thread(file.write, chunk)
        return path
    except MediaSizeLimitExceeded:
        if path:
            path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        if path:
            path.unlink(missing_ok=True)
        logger.warning(f"视频[{url}]下载失败：{exc}")
        return None


async def handle_video_combo(
    url: str,
    img_proxy: bool,
    rss: Optional[Rss] = None,
    headers: Optional[Mapping[str, str]] = None,
) -> str:
    """下载、检查并准备可嵌入 RSS 消息的视频。"""
    path = await download_video(url, img_proxy, headers)
    if path is None:
        return f"\n视频走丢啦 链接：[{url}]\n"

    try:
        segment = await media_delivery.prepare_video_segment(path, path.name)
        return str(segment)
    except MediaSizeLimitExceeded as exc:
        logger.warning(f"视频[{url}]超过发送大小限制，跳过：{exc}")
        return f"\n视频超过大小限制，已跳过：[{url}]\n"
    except Exception as exc:
        logger.warning(f"视频[{url}]处理失败，跳过发送：{exc}")
        return f"\n视频处理失败，已跳过：[{url}]\n"
    finally:
        path.unlink(missing_ok=True)


# 处理图片、视频
async def handle_img(
    item: Dict[str, Any], img_proxy: bool, img_num: int, rss: Optional[Rss] = None
) -> str:
    html = Pq(get_summary(item))
    video_urls = _video_urls(item, html)
    cached_image = ""
    if item.get("image_content"):
        cached_image = await handle_img_combo_with_content(
            item.get("gif_url", ""), item["image_content"], rss
        )
        # 没有视频时保持原有行为：直接使用缓存图片，避免重复下载。
        if not video_urls:
            return cached_image

    img_str = cached_image
    # 处理图片
    doc_img = [] if cached_image else list(html("img").items())
    # 只发送限定数量的图片，防止刷屏
    if 0 < img_num < len(doc_img):
        img_str += f"\n因启用图片数量限制，目前只有 {img_num} 张图片："
        doc_img = doc_img[:img_num]
    for img in doc_img:
        url = img.attr("src")
        img_str += await handle_img_combo(
            url, img_proxy, rss, item.get("image_headers")
        )

    # 处理视频本体；只有没有提取到可下载视频时，才回退发送封面。
    video_str = "".join(
        [
            await handle_video_combo(
                url, img_proxy, rss, item.get("image_headers")
            )
            for url in video_urls
        ]
    )
    if video_str:
        img_str += video_str
    elif html("video"):
        img_str += "\n视频封面："
        for video in html("video").items():
            url = video.attr("poster")
            if url:
                img_str += await handle_img_combo(
                    url, img_proxy, rss, item.get("image_headers")
                )

    return img_str


# 处理 bbcode 图片
async def handle_bbcode_img(
    html: Pq, img_proxy: bool, img_num: int, rss: Optional[Rss] = None
) -> str:
    img_str = ""
    # 处理图片
    img_list = re.findall(r"\[img[^]]*](.+)\[/img]", str(html), flags=re.I)
    # 只发送限定数量的图片，防止刷屏
    if 0 < img_num < len(img_list):
        img_str += f"\n因启用图片数量限制，目前只有 {img_num} 张图片："
        img_list = img_list[:img_num]
    for img_tmp in img_list:
        img_str += await handle_img_combo(img_tmp, img_proxy, rss)

    return img_str


def file_name_format(file_url: URL, rss: Rss) -> Tuple[Path, str]:
    """
    可以根据用户设置的规则来格式化文件名
    """
    format_rule = config.img_format or "{subs}/{name}"
    down_path = config.img_down_path or ""
    rules = {  # 替换格式化字符串
        "{subs}": Rss.handle_name(rss.name),
        "{name}": (
            (file_url.name or "image")
            if "{ext}" not in format_rule
            else Path(file_url.name or "image").stem
        ),
        "{ext}": file_url.suffix if "{ext}" in format_rule else "",
    }
    for k, v in rules.items():
        format_rule = format_rule.replace(k, v)
    if down_path == "":  # 如果没设置保存路径的话,就保存到默认目录下
        save_path = DATA_PATH / "image"
    elif Path(down_path).is_absolute():
        save_path = Path(down_path)
    else:
        save_path = DATA_PATH / Path(down_path)
    full_path = save_path / format_rule
    save_path = full_path.parents[0]
    save_name = full_path.name
    return save_path, save_name


def save_image(content: bytes, file_url: URL, rss: Rss) -> None:
    """
    将压缩之前的原图保存到本地的电脑上
    """
    save_path, save_name = file_name_format(file_url=file_url, rss=rss)

    full_save_path = save_path / save_name
    try:
        full_save_path.write_bytes(content)
    except FileNotFoundError:
        # 初次写入时文件夹不存在,需要创建一下
        save_path.mkdir(parents=True, exist_ok=True)
        full_save_path.write_bytes(content)
