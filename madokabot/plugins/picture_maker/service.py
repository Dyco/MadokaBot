from __future__ import annotations

import base64
import colorsys
import math
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

import httpx
import nonebot_plugin_localstore as store
from nonebot_plugin_alconna import Image as UniImage
from PIL import Image, ImageOps

from madokabot.core.config import config as madoka_config
from madokabot.core.files.cleanup import register_cleanup_path

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
    """使用 MMCQ 候选色和主色调过滤提取 TrackPic 风格的调色板。"""
    sample = image.convert("RGB")
    sample.thumbnail((128, 128), Image.Resampling.LANCZOS)
    if sample.width == 0 or sample.height == 0:
        return ()

    # 直接压成 5 色会让大面积白底吞掉深色和高饱和色。
    # 先生成更多 MMCQ 候选色，再做主色调过滤，保留图片里的颜色层次。
    candidate_count = max(32, count * 8)
    quantized = sample.quantize(colors=candidate_count, method=Image.Quantize.MEDIANCUT)
    colors = quantized.getcolors(maxcolors=sample.width * sample.height) or []
    palette = quantized.getpalette()

    candidates: list[tuple[int, tuple[int, int, int]]] = []
    for population, palette_index in colors:
        offset = palette_index * 3
        rgb = tuple(palette[offset : offset + 3])
        if len(rgb) == 3:
            candidates.append((population, rgb))

    def lightness(rgb: tuple[int, int, int]) -> float:
        red, green, blue = rgb
        return 0.2126 * red + 0.7152 * green + 0.0722 * blue

    def saturation(rgb: tuple[int, int, int]) -> float:
        red, green, blue = (channel / 255 for channel in rgb)
        return colorsys.rgb_to_hsv(red, green, blue)[1]

    def is_pale_neutral(rgb: tuple[int, int, int]) -> bool:
        # 白底、浅灰和压缩产生的近白色不参与前四个主色竞争，
        # 但会保留一个最具代表性的浅色作为最后一个色块。
        return lightness(rgb) >= 205 and saturation(rgb) < 0.16

    def is_near_white(rgb: tuple[int, int, int]) -> bool:
        return min(rgb) >= 248 and max(rgb) - min(rgb) <= 12

    def distance(left: tuple[int, int, int], right: tuple[int, int, int]) -> float:
        return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right)))

    candidates.sort(
        key=lambda item: item[0] * (0.65 + 0.35 * saturation(item[1])),
        reverse=True,
    )
    pale_candidates = [item for item in candidates if is_pale_neutral(item[1])]
    vivid_candidates = [
        item for item in candidates
        if not is_pale_neutral(item[1]) and not is_near_white(item[1])
    ]

    selected: list[tuple[int, int, int]] = []
    for _, rgb in vivid_candidates:
        # 避免 5 个位置被同一段蓝色或同一段灰色占满。
        if any(distance(rgb, existing) < 30 for existing in selected):
            continue
        selected.append(rgb)
        if len(selected) >= max(1, count - 1):
            break

    if pale_candidates and len(selected) < count:
        selected.append(pale_candidates[0][1])

    for _, rgb in candidates:
        if len(selected) >= count:
            break
        if any(distance(rgb, existing) < 24 for existing in selected):
            continue
        selected.append(rgb)

    selected.sort(key=lightness)
    return tuple(f"#{red:02X}{green:02X}{blue:02X}" for red, green, blue in selected[:count])


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
