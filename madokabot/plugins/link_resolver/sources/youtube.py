import asyncio
import uuid
from io import StringIO
from pathlib import Path
from typing import TypedDict

from nonebot import logger

from madokabot.core.messaging.media import MediaSizeLimitExceeded
from madokabot.core.resources import ResourceType, assets

try:
    import yt_dlp
except ImportError:
    yt_dlp = None


def _require_yt_dlp() -> None:
    """检查视频解析所需的 yt-dlp 依赖。"""
    if yt_dlp is None:
        raise RuntimeError("YouTube/TikTok 解析需要安装 yt-dlp")


class VideoInfo(TypedDict):
    """视频基础信息。"""

    title: str
    description: str
    thumbnail: str
    duration: float | None


def _platform_options(video_type: str) -> dict[str, object]:
    """按平台读取统一 Netscape 资源，内存流避免回写原 Cookie 文件。"""
    cookie_name = {"youtube": "ytb_cookies.txt", "tiktok": "tt_cookies.txt"}[video_type]
    cookie_file = assets.get_dir(ResourceType.COOKIES) / cookie_name
    options: dict[str, object] = {
        "cookiefile": StringIO(cookie_file.read_text(encoding="utf-8")),
    }
    if video_type == "youtube":
        options.update(
            js_runtimes={"deno": {}, "node": {}},
            remote_components=["ejs:github"],
        )
    return options


async def get_video_info(
    url: str,
    proxy: str | None = None,
    video_type: str = "youtube",
) -> VideoInfo:
    """使用对应平台的 Cookie 获取视频信息，失败时停止后续下载。"""
    _require_yt_dlp()
    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "noplaylist": True,
        "proxy": proxy or "",
    }

    try:
        ydl_opts.update(_platform_options(video_type))
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = await asyncio.to_thread(ydl.extract_info, url, download=False)
            duration_value = info_dict.get("duration")
            try:
                duration = float(duration_value) if duration_value is not None else None
            except (TypeError, ValueError):
                duration = None
            return {
                "title": str(info_dict.get("title") or "-"),
                "description": str(info_dict.get("description") or ""),
                "thumbnail": str(info_dict.get("thumbnail") or ""),
                "duration": duration,
            }
    except (OSError, ValueError, yt_dlp.utils.DownloadError) as exc:
        raise RuntimeError(f"视频解析失败：{exc}") from exc


async def download_ytb_video(
    url: str,
    path: str | Path,
    proxy: str | None = None,
    video_type: str = "youtube",
    max_size: int | None = None,
) -> str:
    """按选定格式下载视频，并校验累计下载大小。"""
    _require_yt_dlp()
    output_dir = Path(path)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_stem = f"resolver-{uuid.uuid4().hex}"
    downloaded_by_file: dict[str, int] = {}

    def check_download_progress(data: dict) -> None:
        """累计各文件的实际下载量，超过上限时中止。"""
        if max_size is None or data.get("status") != "downloading":
            return
        file_name = str(data.get("tmpfilename") or data.get("filename") or "")
        if not file_name:
            return
        downloaded_by_file[file_name] = max(
            downloaded_by_file.get(file_name, 0),
            int(data.get("downloaded_bytes") or 0),
        )
        if sum(downloaded_by_file.values()) > max_size:
            raise MediaSizeLimitExceeded(
                f"视频下载大小超过上限 {max_size / 1024 / 1024:g} MiB"
            )

    ydl_opts = {
        "outtmpl": str(output_dir / f"{output_stem}.%(ext)s"),
        "merge_output_format": "mp4",
        "noplaylist": True,
        "progress_hooks": [check_download_progress],
        "proxy": proxy or "",
    }
    if max_size is not None:
        ydl_opts["max_filesize"] = max_size
    if video_type == "youtube" and "shorts" not in url:
        ydl_opts["format"] = (
            "bv*[vcodec^=avc1][height<=720]+"
            "ba[acodec^=mp4a]/"
            "b[ext=mp4][vcodec^=avc1][acodec^=mp4a][height<=720]/"
            "bv*[height<=720]+ba/b[height<=720]"
        )
    try:
        ydl_opts.update(_platform_options(video_type))

        def run_download() -> None:
            """校验预计大小后复用解析结果下载，避免重复请求视频信息。"""
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if max_size is not None and isinstance(info, dict):
                    formats = (
                        info.get("requested_downloads")
                        or info.get("requested_formats")
                        or [info]
                    )
                    known_sizes = [
                        int(item.get("filesize") or item.get("filesize_approx") or 0)
                        for item in formats
                        if isinstance(item, dict)
                    ]
                    estimated_size = sum(known_sizes)
                    if estimated_size > max_size:
                        raise MediaSizeLimitExceeded(
                            f"视频预计大小 {estimated_size / 1024 / 1024:.2f} MiB "
                            f"超过上限 {max_size / 1024 / 1024:g} MiB"
                        )
                ydl.process_ie_result(info, download=True)

        await asyncio.to_thread(run_download)
        candidates = [
            candidate
            for candidate in output_dir.glob(f"{output_stem}.*")
            if candidate.is_file()
            and candidate.suffix.lower() not in {".part", ".ytdl"}
        ]
        output_file = next(
            (candidate for candidate in candidates if candidate.suffix == ".mp4"),
            candidates[0] if candidates else None,
        )
        if output_file is None:
            raise RuntimeError("视频下载未生成文件，可能超过大小限制或站点拒绝了请求")
        return str(output_file)
    except Exception as exc:
        logger.error(f"yt-dlp 下载失败: {exc}")
        for candidate in output_dir.glob(f"{output_stem}.*"):
            candidate.unlink(missing_ok=True)
        if isinstance(exc, MediaSizeLimitExceeded):
            raise
        if "超过上限" in str(exc):
            raise MediaSizeLimitExceeded(str(exc)) from exc
        if isinstance(exc, RuntimeError):
            raise
        raise RuntimeError(f"视频下载失败：{exc}") from exc
