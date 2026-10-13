"""按内容与资源指纹持久保存渲染图片。"""

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from tempfile import NamedTemporaryFile

import nonebot_plugin_localstore as store
from PIL import Image

from .json_store import JsonData


def build_image_signature(data: JsonData, files: Iterable[Path] = ()) -> str:
    """根据渲染参数及依赖文件的路径、修改时间和大小生成指纹。"""
    dependencies = []
    for file in files:
        path = file.resolve()
        stat = path.stat()
        dependencies.append((str(path), stat.st_mtime_ns, stat.st_size))
    payload = json.dumps(
        [data, dependencies], ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ImageCache:
    """按业务命名空间和逻辑图片键保存可跨重启复用的 PNG。"""

    def __init__(self, namespace: str) -> None:
        """在公共缓存目录下划分独立的图片存储空间。"""
        self.directory = store.get_cache_dir("madoka_bundle") / "rendered_images" / namespace

    def load(self, key: str, signature: str) -> Image.Image | None:
        """读取匹配指纹的独立图片副本，未命中时返回空值。"""
        path = self.directory / key / f"{signature}.png"
        try:
            with Image.open(path) as image:
                return image.copy()
        except FileNotFoundError:
            return None

    def save(self, key: str, signature: str, image: Image.Image) -> None:
        """原子保存图片，并移除同一逻辑图片键下的旧版本。"""
        directory = self.directory / key
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{signature}.png"
        with NamedTemporaryFile(dir=directory, suffix=".tmp", delete=False) as temporary:
            temporary_path = Path(temporary.name)
        try:
            image.save(temporary_path, format="PNG")
            temporary_path.replace(path)
        finally:
            temporary_path.unlink(missing_ok=True)
        for previous in directory.glob("*.png"):
            if previous != path:
                previous.unlink(missing_ok=True)


__all__ = ["ImageCache", "build_image_signature"]
