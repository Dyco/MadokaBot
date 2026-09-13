import asyncio
import shutil
from collections.abc import Callable
from pathlib import Path

import aiofiles
import httpx
from nonebot import logger

from ..constants import BILIBILI_HEADER
from .downloads import DownloadBudget


async def is_ffmpeg_installed(
    ffmpeg_path: str = "ffmpeg",
    timeout: int = 10,
) -> bool:
    """检查ffmpeg是否安装"""

    # 检查ffmpeg是否在环境变量中
    resolved_path = shutil.which(ffmpeg_path)
    if resolved_path:
        return True

    # 如果仍然未找到，尝试异步调用ffmpeg命令
    try:
        process = await asyncio.create_subprocess_exec(
            ffmpeg_path,
            "-version",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(process.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            if process.returncode is None:
                process.kill()
            await process.wait()
            return False
        if process.returncode == 0:
            return True
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.warning(f"检查ffmpeg时发生错误: {e}")

    return False

async def download_b_file(
    url: str | None,
    full_file_name: str | Path,
    progress_callback: Callable[[str], object] | None = None,
    proxy: str | None = None,
    max_size: int | None = None,
    budget: DownloadBudget | None = None,
) -> bool:
    """
        下载视频文件和音频文件
    :param url:
    :param full_file_name:
    :param progress_callback:
    :return:
    """
    if not url:
        return False

    target = Path(full_file_name)
    target.parent.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(
        headers=BILIBILI_HEADER,
        timeout=60,
        follow_redirects=True,
        proxy=proxy,
        trust_env=False,
    ) as client:
        async with client.stream("GET", url, headers=BILIBILI_HEADER) as resp:
            resp.raise_for_status()
            current_len = 0
            total_len = int(resp.headers.get('content-length', 0))
            if max_size is not None and total_len > max_size:
                raise ValueError(
                    f"视频流大小超过 {max_size / 1024 / 1024:g} MiB"
                )
            async with aiofiles.open(target, "wb") as f:
                async for chunk in resp.aiter_bytes():
                    current_len += len(chunk)
                    if budget is not None:
                        await budget.consume(len(chunk))
                    if max_size is not None and current_len > max_size:
                        raise ValueError(
                            f"视频流下载大小超过 {max_size / 1024 / 1024:g} MiB"
                        )
                    await f.write(chunk)
                    if progress_callback:
                        progress = current_len / total_len if total_len else 0
                        progress_callback(f'下载进度：{progress:.3f}')
    return True


async def merge_file_to_mp4(
    v_full_file_name: str,
    a_full_file_name: str | None,
    output_file_name: str,
    log_output: bool = False,
    ffmpeg_path: str = "ffmpeg",
    timeout: int = 1800,
    transcode_video: bool = False,
):
    """
    合并视频文件和音频文件
    :param v_full_file_name: 视频文件路径
    :param a_full_file_name: 音频文件路径
    :param output_file_name: 输出文件路径
    :param log_output: 是否显示 ffmpeg 输出日志，默认忽略
    :return:
    """
    logger.info(f'正在合并：{output_file_name}')

    # 检查 ffmpeg 是否安装
    if not await is_ffmpeg_installed(ffmpeg_path, min(timeout, 10)):
        logger.error('ffmpeg 未安装，请先安装 ffmpeg 并配置环境变量。可参考插件主页说明。')
        raise RuntimeError(f"找不到 ffmpeg：{ffmpeg_path}")

    # 使用参数列表构建命令，避免标题或路径中的字符被 shell 解释。
    command = [ffmpeg_path, "-y", "-i", v_full_file_name]
    if a_full_file_name:
        command.extend(["-i", a_full_file_name])
    if transcode_video:
        command.extend(["-map", "0:v:0"])
        command.extend(
            ["-map", "1:a:0?"]
            if a_full_file_name
            else ["-map", "0:a:0?"]
        )
        command.extend(
            [
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "23",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                output_file_name,
            ]
        )
    else:
        command.extend(["-c", "copy", output_file_name])
    output_target = None if log_output else asyncio.subprocess.DEVNULL
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=output_target,
        stderr=output_target,
    )
    try:
        return_code = await asyncio.wait_for(process.wait(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise RuntimeError(f"ffmpeg 合并 Bilibili 视频超过 {timeout} 秒") from exc
    except asyncio.CancelledError:
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise
    if return_code != 0:
        raise RuntimeError(f"ffmpeg 合并 Bilibili 视频失败，退出码: {return_code}")
    return output_file_name


def extra_bili_info(video_info):
    """
        格式化视频信息
    """
    video_state = video_info['stat']
    video_like, video_coin, video_favorite, video_share, video_view, video_danmaku, video_reply = video_state['like'], \
        video_state['coin'], video_state['favorite'], video_state['share'], video_state['view'], video_state['danmaku'], \
        video_state['reply']

    video_data_map = {
        "点赞": video_like,
        "硬币": video_coin,
        "收藏": video_favorite,
        "分享": video_share,
        "总播放量": video_view,
        "弹幕数量": video_danmaku,
        "评论": video_reply
    }

    video_info_result = ""
    for key, value in video_data_map.items():
        if int(value) > 10000:
            formatted_value = f"{value / 10000:.1f}万"
        else:
            formatted_value = value
        video_info_result += f"{key}: {formatted_value} | "

    return video_info_result
