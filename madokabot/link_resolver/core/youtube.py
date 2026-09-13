import asyncio
from pathlib import Path

from nonebot import logger

try:
    import yt_dlp
except ImportError:  # yt-dlp 仅在用户启用对应平台时需要。
    yt_dlp = None


def _require_yt_dlp() -> None:
    if yt_dlp is None:
        raise RuntimeError("YouTube/TikTok 解析需要安装 yt-dlp")


async def get_video_title(
    url: str,
    is_oversea: bool,
    my_proxy: str | None = None,
    video_type: str = "youtube",
) -> str:
    _require_yt_dlp()
    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "force_generic_extractor": True,
    }
    if not is_oversea and my_proxy:
        ydl_opts["proxy"] = my_proxy

    cookie_file = Path.cwd() / "ytb_cookies.txt"
    if video_type == "youtube" and cookie_file.is_file():
        ydl_opts["cookiefile"] = str(cookie_file)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = await asyncio.to_thread(ydl.extract_info, url, download=False)
            return info_dict.get("title", "-")
    except Exception as exc:
        logger.error(f"yt-dlp 获取标题失败: {exc}")
        return "-"


async def download_ytb_video(
    url: str,
    is_oversea: bool,
    path: str | Path,
    my_proxy: str | None = None,
    video_type: str = "youtube",
    max_size: int | None = None,
) -> str | None:
    _require_yt_dlp()
    output_dir = Path(path)
    output_dir.mkdir(parents=True, exist_ok=True)
    ydl_opts = {
        "outtmpl": str(output_dir / "temp.%(ext)s"),
        "merge_output_format": "mp4",
    }
    if max_size is not None:
        ydl_opts["max_filesize"] = max_size
    cookie_file = Path.cwd() / "ytb_cookies.txt"
    if video_type == "youtube":
        if cookie_file.is_file():
            ydl_opts["cookiefile"] = str(cookie_file)
        if "shorts" not in url:
            ydl_opts["format"] = "bv*[width=1280][height=720]+ba"
    if not is_oversea and my_proxy:
        ydl_opts["proxy"] = my_proxy

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            await asyncio.to_thread(ydl.download, [url])
        output_file = output_dir / "temp.mp4"
        return str(output_file) if output_file.is_file() else None
    except Exception as exc:
        logger.error(f"yt-dlp 下载失败: {exc}")
        return None
