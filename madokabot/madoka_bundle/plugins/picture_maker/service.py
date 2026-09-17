from __future__ import annotations

import base64
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

import httpx
import nonebot_plugin_localstore as store
from nonebot_plugin_alconna import Image as UniImage
from PIL import Image, ImageOps

from ...config import config as madoka_config
from ..common import register_cleanup_path

_CACHE_DIR = store.get_cache_dir("picture_maker")
_CACHE_DIR.mkdir(parents=True, exist_ok=True)
register_cleanup_path("picture-maker", _CACHE_DIR)

_MAX_SOURCE_SIZE = 20 * 1024 * 1024
_MAX_IMAGE_PIXELS = 20_000_000
_MAX_IMAGE_DIMENSION = 2560
_DOWNLOAD_TIMEOUT = 20.0
_PROXY_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)


@dataclass(frozen=True)
class PreparedImage:
    """记录规范化图片及其对应的临时文件。"""

    path: Path
    temporary_paths: tuple[Path, ...]
    palette: tuple[str, ...] = ()

    @property
    def data_url(self) -> str:
        """将规范化后的图片转换为 HTML 可直接使用的 Data URL。"""
        encoded = base64.b64encode(self.path.read_bytes()).decode("ascii")
        return f"data:image/png;base64,{encoded}"


def _extract_palette(image: Image.Image, count: int = 5) -> tuple[str, ...]:
    """从图片中提取与 TrackPic 类似的主色调。"""
    sample = image.convert("RGB")
    sample.thumbnail((128, 128), Image.Resampling.LANCZOS)
    if sample.width == 0 or sample.height == 0:
        return ()

    quantized = sample.quantize(colors=count, method=Image.Quantize.MEDIANCUT)
    colors = quantized.getcolors(maxcolors=sample.width * sample.height) or []
    colors.sort(reverse=True)
    palette = quantized.getpalette()

    result: list[str] = []
    for _, palette_index in colors[:count]:
        offset = palette_index * 3
        red, green, blue = palette[offset : offset + 3]
        result.append(f"#{red:02X}{green:02X}{blue:02X}")
    return tuple(result)


def _normalize_proxy_url(proxy: str | None) -> str | None:
    """将主配置中的代理地址规范化为 httpx 可识别的 URL。"""
    value = str(proxy or "").strip()
    if not value:
        return None
    if _PROXY_SCHEME_RE.match(value):
        return value
    return f"http://{value}"


async def _read_image_source(image: UniImage) -> bytes:
    """读取 Alconna 图片对象中的原始图片数据。"""
    raw = image.raw
    if raw is not None:
        if isinstance(raw, bytes):
            return raw
        if isinstance(raw, bytearray):
            return bytes(raw)
        if hasattr(raw, "getvalue"):
            return raw.getvalue()
        if hasattr(raw, "read"):
            return raw.read()

    if image.path:
        path = Path(image.path)
        if path.is_file():
            return path.read_bytes()

    if image.url:
        proxy = _normalize_proxy_url(madoka_config.proxy)
        async with httpx.AsyncClient(
            proxy=proxy,
            trust_env=False,
            follow_redirects=True,
            timeout=_DOWNLOAD_TIMEOUT,
        ) as client:
            response = await client.get(str(image.url))
            response.raise_for_status()
            if len(response.content) > _MAX_SOURCE_SIZE:
                raise ValueError("图片文件过大")
            return response.content

    raise ValueError("无法读取图片数据")


def _normalize_image(source_path: Path, output_path: Path) -> None:
    """校验图片并缩放为适合 HTML 渲染的 PNG。"""
    with Image.open(source_path) as source:
        if source.width * source.height > _MAX_IMAGE_PIXELS:
            raise ValueError("图片像素过高")

        source.load()
        image = ImageOps.exif_transpose(source).convert("RGBA")
        image.thumbnail(
            (_MAX_IMAGE_DIMENSION, _MAX_IMAGE_DIMENSION),
            Image.Resampling.LANCZOS,
        )
        image.save(output_path, format="PNG", optimize=True)


async def prepare_image(image: UniImage) -> PreparedImage:
    """下载、校验并规范化用户发送的图片。"""
    data = await _read_image_source(image)
    if not data:
        raise ValueError("图片内容为空")
    if len(data) > _MAX_SOURCE_SIZE:
        raise ValueError("图片文件过大")

    token = uuid.uuid4().hex
    source_path = _CACHE_DIR / f"{token}.source"
    output_path = _CACHE_DIR / f"{token}.png"
    temporary_paths = (source_path, output_path)

    try:
        source_path.write_bytes(data)
        _normalize_image(source_path, output_path)
        with Image.open(output_path) as normalized:
            palette = _extract_palette(normalized)
        return PreparedImage(output_path, temporary_paths, palette)
    except Exception:
        cleanup_image(PreparedImage(output_path, temporary_paths))
        raise


def cleanup_image(image: PreparedImage) -> None:
    """删除本次制图使用的临时文件。"""
    for path in image.temporary_paths:
        path.unlink(missing_ok=True)
