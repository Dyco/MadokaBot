"""RSS 插件使用的 aria2 RPC 客户端。"""

import asyncio
import base64
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import aiohttp

from .config import config


class Aria2Error(RuntimeError):
    """aria2 RPC 或下载任务返回的错误。"""


class DownloadAcquireTimeout(Aria2Error):
    """下载链接、种子文件或磁力元数据获取超时。"""


ARIA2_STATUS_FIELDS = [
    "status",
    "errorCode",
    "errorMessage",
    "totalLength",
    "completedLength",
    "downloadSpeed",
    "seeder",
    "dir",
    "files",
    "bittorrent",
    "infoHash",
    "followedBy",
]


def _rpc_url() -> str:
    """生成 aria2 JSON-RPC 地址。"""
    url = str(config.aria2_rpc_url or "http://127.0.0.1:6800/jsonrpc").strip()
    if not url:
        return "http://127.0.0.1:6800/jsonrpc"
    if not url.rstrip("/").endswith("/jsonrpc"):
        url = f"{url.rstrip('/')}/jsonrpc"
    return url


def _rpc_params(params: Sequence[Any]) -> List[Any]:
    """为 RPC 参数附加可选密钥。"""
    result = list(params)
    if config.aria2_rpc_secret:
        result.insert(0, f"token:{config.aria2_rpc_secret}")
    return result


async def _rpc_call(method: str, params: Sequence[Any] = ()) -> Any:
    """调用 aria2 JSON-RPC 并统一转换请求错误。"""
    payload = {
        "jsonrpc": "2.0",
        "id": "madokabot-rss",
        "method": method,
        "params": _rpc_params(params),
    }
    timeout = aiohttp.ClientTimeout(total=config.aria2_acquire_timeout)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(_rpc_url(), json=payload) as response:
                response.raise_for_status()
                result = await response.json()
    except asyncio.TimeoutError as exc:
        raise DownloadAcquireTimeout(
            f"aria2 RPC 请求超过 {config.aria2_acquire_timeout} 秒"
        ) from exc
    except aiohttp.ClientError as exc:
        raise Aria2Error(f"无法连接 aria2 RPC：{exc}") from exc
    except ValueError as exc:
        raise Aria2Error("aria2 RPC 返回了无效的 JSON") from exc

    if not isinstance(result, dict):
        raise Aria2Error("aria2 RPC 返回格式错误")
    if error := result.get("error"):
        if isinstance(error, dict):
            code = error.get("code", "?")
            message = error.get("message", "未知错误")
            raise Aria2Error(f"aria2 错误[{code}]：{message}")
        raise Aria2Error(f"aria2 错误：{error}")
    if "result" not in result:
        raise Aria2Error("aria2 RPC 返回中缺少 result")
    return result["result"]


def _download_options(proxy: Optional[str] = None) -> Dict[str, str]:
    """生成新任务的 aria2 下载参数。"""
    options: Dict[str, str] = {
        "seed-time": "0",
        "bt-save-metadata": "true",
    }
    if config.aria2_download_path:
        download_path = Path(config.aria2_download_path).expanduser().resolve()
        try:
            download_path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise Aria2Error(
                f"无法创建 aria2 下载目录：{download_path}：{exc}"
            ) from exc
        options["dir"] = str(download_path)
    if proxy:
        options["all-proxy"] = proxy
    return options


async def _fetch_torrent(url: str, proxy: Optional[str]) -> bytes:
    """获取 torrent 文件原始内容。"""
    timeout = aiohttp.ClientTimeout(total=config.aria2_acquire_timeout)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, proxy=proxy) as response:
                response.raise_for_status()
                return await response.read()
    except asyncio.TimeoutError as exc:
        raise DownloadAcquireTimeout(
            f"torrent 文件获取超过 {config.aria2_acquire_timeout} 秒"
        ) from exc
    except aiohttp.ClientError as exc:
        raise Aria2Error(f"下载 torrent 文件失败：{exc}") from exc


async def aria2_version() -> str:
    """读取 aria2 服务版本。"""
    result = await _rpc_call("aria2.getVersion")
    if isinstance(result, dict):
        return str(result.get("version", "unknown"))
    return "unknown"


async def add_download(
    url: str,
    proxy: Optional[str] = None,
) -> tuple[str, Optional[bytes]]:
    """把磁力链接或 torrent 地址提交给 aria2，并保留原种子内容。"""
    options = _download_options(proxy)
    torrent_content: Optional[bytes] = None
    if url.lower().startswith("magnet:?"):
        # 元数据本身仍需下载，实际 BT 任务保持暂停直至完成大小校验。
        options["pause-metadata"] = "true"
        result = await _rpc_call("aria2.addUri", [[url], options])
    else:
        options["pause"] = "true"
        torrent_content = await _fetch_torrent(url, proxy)
        torrent = base64.b64encode(torrent_content).decode("ascii")
        result = await _rpc_call("aria2.addTorrent", [torrent, [], options])
    if not isinstance(result, str) or not result:
        raise Aria2Error(f"aria2 未返回有效 GID：{result!r}")
    return result, torrent_content


async def get_status(gid: str) -> Dict[str, Any]:
    """读取指定 GID 的 aria2 任务状态。"""
    result = await _rpc_call("aria2.tellStatus", [gid, ARIA2_STATUS_FIELDS])
    if not isinstance(result, dict):
        raise Aria2Error(f"aria2 任务状态格式错误：{result!r}")
    return result
