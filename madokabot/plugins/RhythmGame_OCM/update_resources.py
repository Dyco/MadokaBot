"""舞萌与中二资源增量更新工具，可直接运行，无需启动机器人或提供 Token。"""

import argparse
import json
import threading
import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from typing import Literal

import httpx
from PIL import Image

Game = Literal["maimai", "chunithm"]
API_BASE = "https://maimai.lxns.net/api/v0"
ASSET_BASE = "https://assets2.lxns.net"
_download_lock = threading.Lock()
_last_download = 0.0


def pace_download(interval: float) -> None:
    """共用请求间隔，少量并发下载仍遵守资源服务器访问频率。"""
    global _last_download
    with _download_lock:
        time.sleep(max(0, _last_download + interval - time.monotonic()))
        _last_download = time.monotonic()


def local_image(image_root: Path, kind: str, resource_id: int) -> Path | None:
    """查找有效本地素材，排除资源包内复制的默认曲绘。"""
    folder = "cover" if kind == "jacket" else kind
    path = image_root / folder / f"{resource_id}.png"
    if not path.is_file():
        return None
    placeholder = image_root / "cover" / "0.png"
    if (
        kind == "jacket" and placeholder.is_file()
        and path.stat().st_size == placeholder.stat().st_size
        and path.read_bytes() == placeholder.read_bytes()
    ):
        return None
    return path


def read_catalog(data_root: Path) -> dict:
    """读取本地曲目快照，首次更新前返回空目录。"""
    path = data_root / "catalog.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def refresh_catalog(client: httpx.Client, data_root: Path, *, game: Game = "maimai") -> dict:
    """从公共接口刷新曲目和定数，原子保存 UTF-8 快照。"""
    response = client.get(f"{API_BASE}/{game}/song/list", params={"notes": "true"})
    response.raise_for_status()
    payload = response.json()
    if "success" in payload:
        if not payload["success"]:
            raise ValueError("LXNS 曲目数据更新失败，请稍后重试。")
        payload = payload["data"]
    catalog = {"updated_at": time.time(), **payload}
    data_root.mkdir(parents=True, exist_ok=True)
    temporary = data_root / "catalog.json.tmp"
    temporary.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(data_root / "catalog.json")
    return catalog


def download_image(
    client: httpx.Client,
    image_root: Path,
    kind: str,
    resource_id: int,
    interval: float,
    *,
    game: Game = "maimai",
) -> Path | None:
    """仅下载缺失素材，限速并校验图片，远端未收录时保留本地占位。"""
    existing = local_image(image_root, kind, resource_id)
    if existing:
        return existing
    pace_download(interval)
    response = client.get(f"{ASSET_BASE}/{game}/{kind}/{resource_id}.png")
    if response.status_code == 404:
        return None
    response.raise_for_status()
    with Image.open(BytesIO(response.content)) as picture:
        picture.verify()
    folder = "cover" if kind == "jacket" else kind
    path = image_root / folder / f"{resource_id}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".png.tmp")
    temporary.write_bytes(response.content)
    temporary.replace(path)
    return path


def jacket_ids(catalog: dict, game: Game) -> list[int]:
    """提取曲绘 ID，中二 WORLD'S END 复用原曲曲绘。"""
    if game == "maimai":
        return sorted({int(song["id"]) for song in catalog["songs"] if int(song["id"]) < 100000})
    identifiers = set()
    for song in catalog["songs"]:
        for chart in song["difficulties"]:
            identifiers.add(int(chart["origin_id"] if chart["difficulty"] == 5 else song["id"]))
    return sorted(identifiers)


def update_resources(
    image_root: Path, data_root: Path, *, timeout: float = 20, interval: float = 1,
    game: Game = "maimai",
) -> dict[str, int]:
    """更新曲目快照并增量补齐曲绘，已有素材不重复下载。"""
    counts = {"songs": 0, "downloaded": 0, "existing": 0, "unavailable": 0}
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        catalog = refresh_catalog(client, data_root, game=game)
        song_ids = jacket_ids(catalog, game)
        counts["songs"] = len(catalog["songs"])
        missing = [song_id for song_id in song_ids if not local_image(image_root, "jacket", song_id)]
        counts["existing"] = len(song_ids) - len(missing)

        def record_download(song_id: int, future: Future) -> None:
            """统计已完成下载并输出进度，异常时停止提交后续请求。"""
            path = future.result()
            counts["downloaded" if path else "unavailable"] += 1
            print(f"曲绘 {song_id}：{'已下载' if path else '远端未收录'}", flush=True)

        # 最多保留三个下载请求，避免网络延迟放大全量更新耗时。
        with ThreadPoolExecutor(max_workers=3) as pool:
            pending = deque()
            for song_id in missing:
                if len(pending) == 3:
                    record_download(*pending.popleft())
                pending.append((song_id, pool.submit(
                    download_image, client, image_root, "jacket", song_id, interval, game=game,
                )))
            for item in pending:
                record_download(*item)
    return counts


def main() -> None:
    """通过命令行按游戏更新指定资源根目录中的曲目与曲绘。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--assets-dir", type=Path, default=Path(__file__).resolve().parents[3] / "assets"
    )
    parser.add_argument("--interval", type=float, default=1, help="下载间隔秒数，至少 0.5")
    parser.add_argument("--game", choices=("maimai", "chunithm"), default="maimai")
    args = parser.parse_args()
    if args.interval < 0.5:
        parser.error("下载间隔不能低于 0.5 秒")
    result = update_resources(
        args.assets_dir / "image" / args.game,
        args.assets_dir / "json" / args.game,
        interval=args.interval,
        game=args.game,
    )
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
