import json
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import urljoin

import httpx

headers = {
    'referer': 'https://www.acfun.cn/',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.83'
}


def parse_url(url: str, proxy: str | None = None):
    """
        解析acfun链接
    :param url:
    :return:
    """
    url_suffix = "?quickViewId=videoInfo_new&ajaxpipe=1"
    url = url + url_suffix
    # print(url)

    response = httpx.get(
        url,
        headers=headers,
        timeout=20,
        follow_redirects=True,
        proxy=proxy,
        trust_env=False,
    )
    response.raise_for_status()
    raw = response.text
    strs_remove_header = raw.split("window.pageInfo = window.videoInfo =")
    strs_remove_tail = strs_remove_header[1].split("</script>")
    str_json = strs_remove_tail[0]
    str_json_escaped = escape_special_chars(str_json)
    video_info = json.loads(str_json_escaped)
    # print(video_info)
    video_name = parse_video_name_fixed(video_info)
    ks_play_json = video_info['currentVideoInfo']['ksPlayJson']
    ks_play = json.loads(ks_play_json)
    representations = ks_play['adaptationSet'][0]['representation']
    if not representations:
        raise ValueError("ACFun 没有返回可用的视频流")
    # 这里[d['url'] for d in representations]，从4k~360，此处默认720p
    url_m3u8s = representations[min(3, len(representations) - 1)]['url']
    # print([d['url'] for d in representations])
    return url_m3u8s, video_name


def parse_m3u8(m3u8_url: str, proxy: str | None = None):
    """
        解析m3u8链接
    :param m3u8_url:
    :return:
    """
    response = httpx.get(
        m3u8_url,
        headers=headers,
        timeout=20,
        follow_redirects=True,
        proxy=proxy,
        trust_env=False,
    )
    response.raise_for_status()
    m3u8_file = response.text
    # 分离ts文件链接
    raw_pieces = re.split(r"\n#EXTINF:.{8},\n", m3u8_file)
    # print(raw_pieces)
    # 过滤头部\
    m3u8_relative_links = [piece.split("\n")[0].strip() for piece in raw_pieces[1:]]
    # print(m3u8_relative_links)
    # 修改尾部 去掉尾部多余的结束符
    if not m3u8_relative_links:
        raise ValueError("ACFun m3u8 未返回可下载的视频分片")
    # print(m3u8_relative_links)

    # 完整链接，直接加m3u8Url的通用前缀
    m3u8_full_urls = [urljoin(m3u8_url, item) for item in m3u8_relative_links]
    # aria2c下载的文件名，就是取url最后一段，去掉末尾url参数(?之后是url参数)
    ts_names = [d.split("?")[0] for d in m3u8_relative_links]
    # print(ts_names)
    first_segment_name = Path(ts_names[0]).name
    output_stem = first_segment_name[:-9] or Path(first_segment_name).stem
    output_folder_name = re.sub(
        r"[^0-9A-Za-z\u4e00-\u9fff._-]+",
        "_",
        output_stem,
    ).strip("._") or "acfun_video"
    output_file_name = output_folder_name + ".mp4"
    # print(output_file_name)
    return m3u8_full_urls, ts_names, output_folder_name, output_file_name


async def download_m3u8_videos(
    m3u8_full_url: str,
    i: int,
    output_dir: str | os.PathLike[str] | None = None,
    proxy: str | None = None,
):
    """
        批量下载m3u8
    :param m3u8_full_urls:
    :return:
    """
    target_dir = Path(output_dir or Path.cwd())
    target_dir.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(
        headers=headers,
        timeout=60,
        follow_redirects=True,
        proxy=proxy,
        trust_env=False,
    ) as client:
        async with client.stream("GET", m3u8_full_url, headers=headers) as resp:
            resp.raise_for_status()
            with (target_dir / f"{i}.ts").open("wb") as f:
                async for chunk in resp.aiter_bytes():
                    f.write(chunk)


def escape_special_chars(str_json):
    return str_json.replace('\\\\"', '\\"').replace('\\"', '"')


def parse_video_name(video_info: dict) -> str:
    """
        获取视频信息
    :param video_info:
    :return:
    """
    ac_id = "ac" + video_info['dougaId'] if video_info['dougaId'] is not None else ""
    title = video_info['title'] if video_info['title'] is not None else ""
    author = video_info['user']['name'] if video_info['user']['name'] is not None else ""
    upload_time = video_info['createTime'] if video_info['createTime'] is not None else ""
    desc = video_info['description'] if video_info['description'] is not None else ""

    raw = '_'.join([ac_id, title, author, upload_time, desc])[:101]
    return raw


def merge_ac_file_to_mp4(
    ts_names,
    full_file_name: str | os.PathLike[str],
    should_delete: bool = True,
    work_dir: str | os.PathLike[str] | None = None,
):
    work_path = Path(work_dir or Path.cwd())
    work_path.mkdir(parents=True, exist_ok=True)
    output_path = Path(full_file_name)
    if not output_path.is_absolute():
        output_path = work_path / output_path
    manifest_path = work_path / "resolver_concat.txt"
    concat_str = "\n".join(
        f"file '{(work_path / f'{index}.ts').as_posix()}'"
        for index, _ in enumerate(ts_names)
    )
    manifest_path.write_text(concat_str, encoding="utf-8")

    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(manifest_path),
            "-c",
            "copy",
            str(output_path),
        ],
        cwd=work_path,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg 合并 ACFun 视频失败，退出码: {result.returncode}")
    if should_delete:
        manifest_path.unlink(missing_ok=True)
        for index in range(len(ts_names)):
            (work_path / f"{index}.ts").unlink(missing_ok=True)
    return str(output_path)


def parse_video_name_fixed(video_info: dict) -> str:
    """
        校准文件名
    :param video_info:
    :return:
    """
    f = parse_video_name(video_info)
    t = f.replace(" ", "-")
    return t
