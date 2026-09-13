"""Resolver 的临时资源下载与文件清理工具。"""

import asyncio
import os
import re
import time
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import aiofiles
import aiohttp
import httpx
import nonebot_plugin_localstore as store
from nonebot import logger, require

from ..constants import COMMON_HEADER, PLUGIN_NAME

require("nonebot_plugin_localstore")

CACHE_DIR = Path(store.get_cache_dir(PLUGIN_NAME))
CACHE_DIR.mkdir(parents=True, exist_ok=True)


class DownloadBudget:
    """为并发分片或音视频流共享一个实际下载字节上限。"""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.downloaded = 0
        self._lock = asyncio.Lock()

    async def consume(self, size: int) -> None:
        async with self._lock:
            if self.downloaded + size > self.limit:
                raise ValueError(
                    f"视频下载大小超过上限 {self.limit / 1024 / 1024:g} MiB"
                )
            self.downloaded += size


async def ensure_remote_total_within_limit(
    urls: Iterable[str],
    limit: int,
    proxy: str | None = None,
    headers: dict[str, str] | None = None,
) -> None:
    """在服务器提供 Content-Length 时，于下载正文前校验总大小。"""
    url_list = [url for url in urls if url]
    if not url_list:
        return

    client_headers = COMMON_HEADER.copy()
    if headers:
        client_headers.update(headers)
    async with httpx.AsyncClient(
        headers=client_headers,
        timeout=httpx.Timeout(20, connect=5.0),
        follow_redirects=True,
        proxy=proxy,
        trust_env=False,
    ) as client:
        semaphore = asyncio.Semaphore(8)

        async def content_length(url: str) -> int | None:
            try:
                async with semaphore:
                    response = await client.head(url)
                response.raise_for_status()
                size = int(response.headers.get("content-length") or 0)
                return size if size > 0 else None
            except (httpx.HTTPError, TypeError, ValueError):
                return None

        sizes = await asyncio.gather(*(content_length(url) for url in url_list))

    known_total = sum(size for size in sizes if size is not None)
    if known_total > limit:
        raise ValueError(
            f"视频已知总大小 {known_total / 1024 / 1024:.2f} MiB "
            f"超过上限 {limit / 1024 / 1024:g} MiB"
        )


async def download_video(
    url: str,
    proxy: str | None = None,
    ext_headers: dict[str, str] | None = None,
    max_size: int | None = None,
) -> str | None:
    """下载视频到 Resolver 缓存目录。"""
    path = CACHE_DIR / f"{time.time_ns()}.mp4"
    headers = COMMON_HEADER.copy()
    if ext_headers:
        headers.update(ext_headers)

    client_options: dict[str, Any] = {
        "headers": headers,
        "timeout": httpx.Timeout(60, connect=5.0),
        "follow_redirects": True,
        "trust_env": False,
    }
    if proxy:
        client_options["proxy"] = proxy

    try:
        async with httpx.AsyncClient(**client_options) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                content_length = response.headers.get("content-length")
                try:
                    expected_size = int(content_length or 0)
                except ValueError:
                    expected_size = 0
                if (
                    max_size is not None
                    and expected_size > max_size
                ):
                    raise ValueError(
                        f"视频大小 {expected_size / 1024 / 1024:.2f} MiB "
                        f"超过上限 {max_size / 1024 / 1024:g} MiB"
                    )
                downloaded = 0
                async with aiofiles.open(path, "wb") as file:
                    async for chunk in response.aiter_bytes():
                        downloaded += len(chunk)
                        if max_size is not None and downloaded > max_size:
                            raise ValueError(
                                f"视频下载大小超过上限 "
                                f"{max_size / 1024 / 1024:g} MiB"
                            )
                        await file.write(chunk)
        return str(path)
    except ValueError:
        path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        logger.warning(f"下载视频失败：{exc}")
        path.unlink(missing_ok=True)
        return None


async def download_image(
    url: str,
    path: str = "",
    proxy: str | None = None,
    session: aiohttp.ClientSession | None = None,
    headers: dict[str, str] | None = None,
) -> str:
    """下载图片；传入 session 时复用已有连接。"""
    if not path:
        file_name = Path(urlparse(url).path).name or f"{time.time_ns()}.img"
        path = str(CACHE_DIR / f"{time.time_ns()}_{file_name}")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    async def save_response(response: aiohttp.ClientResponse) -> None:
        response.raise_for_status()
        async with aiofiles.open(target, "wb") as file:
            await file.write(await response.read())

    if session is None:
        async with aiohttp.ClientSession() as own_session:
            async with own_session.get(
                url,
                proxy=proxy,
                headers=headers,
            ) as response:
                await save_response(response)
    else:
        async with session.get(url, proxy=proxy, headers=headers) as response:
            await save_response(response)
    return path


async def download_audio(url: str, proxy: str | None = None) -> str:
    """下载音频到 Resolver 缓存目录。"""
    file_name = Path(urlparse(url).path).name or f"{time.time_ns()}.audio"
    path = CACHE_DIR / f"{time.time_ns()}_{file_name}"
    async with httpx.AsyncClient(proxy=proxy, trust_env=False) as client:
        response = await client.get(url)
        response.raise_for_status()
        async with aiofiles.open(path, "wb") as file:
            await file.write(response.content)
    return str(path)


def clean_title(value: str) -> str:
    """删除不适合用作简短标题的特殊字符。"""
    return re.sub(
        r"[0-9’!\"∀〃#$%&'()*+,-./:;<=>?@，。?★、…【】《》？“”‘’！[\\]^_`{|}~～\s]+",
        "",
        value,
    )


def remove_files(file_paths: Iterable[str | os.PathLike[str]]) -> dict[str, str]:
    """删除一组临时文件，并返回各路径的处理结果。"""
    results: dict[str, str] = {}
    for file_path in file_paths:
        path = Path(file_path)
        if not path.exists():
            results[str(path)] = "not_found"
            continue
        try:
            path.unlink()
            results[str(path)] = "removed"
        except OSError as exc:
            results[str(path)] = f"error: {exc}"
    return results
