import re
import time
from functools import partial
from html import unescape
from typing import Any

from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupMessageEvent,
    Message,
    MessageEvent,
)
from nonebot.matcher import Matcher
from nonebot.params import ArgPlainText
from nonebot_plugin_alconna import Match as AlcMatch, UniMessage
from nonebot_plugin_waiter import waiter

from ..download import (
    Aria2Error,
    DownloadSizeLimitExceeded,
    DownloadStatus,
    cancel_download,
    delete_download_files,
    download_tasks,
    retry_upload_to_group,
    select_download_files,
    start_download,
)
from ..utils import get_proxy
from .matchers import (
    rss_close_cmd,
    rss_delete_file_cmd,
    rss_retry_upload_cmd,
    rss_select_file_cmd,
    rss_upload_cmd,
)


FILE_SELECTION_TIMEOUT = 60.0


def _extract_download_url(content: str) -> str | None:
    """提取完整磁链或 torrent 地址，保留 tracker 等查询参数。"""
    content = unescape(content.strip())
    target = re.search(r"magnet:\?[^\s]+", content, flags=re.I)
    if target is None:
        target = re.search(
            r"https?://[^\s]+?\.torrent(?:\?[^\s]*)?",
            content,
            flags=re.I,
        )
    if target is None:
        return None
    return target.group(0).rstrip(".,;:，。；：)]}】》>")


def _message_ids(send_results: list[dict[str, Any]]) -> set[int]:
    message_ids: set[int] = set()
    for result in send_results:
        try:
            message_ids.add(int(result["message_id"]))
        except (KeyError, TypeError, ValueError):
            continue
    return message_ids


async def _wait_for_file_selection(
    bot: Bot,
    gid: str,
    prompt_results: list[dict[str, Any]],
    group_ids: list[str],
    name: str,
    *,
    user_id: str,
) -> None:
    """等待上传发起者引用文件列表提示并回复文件编号。"""
    prompt_message_ids = _message_ids(prompt_results)
    if not prompt_message_ids:
        return

    @waiter(waits=["message"], matcher=rss_upload_cmd, block=True)
    async def wait_selection(reply_event: MessageEvent):
        if not isinstance(reply_event, GroupMessageEvent) or not reply_event.reply:
            return None
        if reply_event.get_user_id() != user_id:
            return None
        if str(reply_event.group_id) not in group_ids:
            return None
        try:
            replied_message_id = int(reply_event.reply.message_id)
        except (TypeError, ValueError):
            return None
        if replied_message_id not in prompt_message_ids:
            return None
        return reply_event, reply_event.get_plaintext().strip()

    deadline = time.monotonic() + FILE_SELECTION_TIMEOUT
    while (remaining := deadline - time.monotonic()) > 0:
        reply = await wait_selection.wait(timeout=remaining)
        if reply is None:
            return

        reply_event, selection = reply
        task_info = download_tasks.get(gid)
        if task_info is None or task_info.get("status") != DownloadStatus.WAITING_SELECTION:
            return
        try:
            result = await select_download_files(
                bot=bot,
                gid=gid,
                selection=selection,
                group_ids=group_ids,
                name=name,
            )
        except DownloadSizeLimitExceeded as exc:
            await UniMessage(f"❌ 已拒绝下载：\n{exc}").send(
                target=reply_event,
                reply_to=True,
            )
            return
        except Aria2Error as exc:
            await UniMessage(
                f"❌ 选择文件失败：{exc}\n请继续引用原提示重新输入。"
            ).send(target=reply_event, reply_to=True)
            continue

        await UniMessage(
            f"已选择 {result['selected_count']} 个文件，开始下载。\n"
            f"{result['summary']}"
        ).send(target=reply_event, reply_to=True)
        return


@rss_upload_cmd.handle()
async def handle_upload_file(
    bot: Bot, event: GroupMessageEvent, content: AlcMatch[str]
) -> None:
    target = _extract_download_url(
        content.result if content.available else ""
    )
    if not target:
        await rss_upload_cmd.finish("请输入种子链接")
        return
    await start_download(
        bot=bot,
        url=target,
        group_ids=[str(event.group_id)],
        name="手动上传",
        proxy=get_proxy(),
        manual_selection=True,
        selection_handler=partial(
            _wait_for_file_selection,
            user_id=event.get_user_id(),
        ),
    )


@rss_select_file_cmd.handle()
async def prepare_select_files(matcher: Matcher, content: AlcMatch[str]) -> None:
    if content.available and content.result.strip():
        matcher.set_arg("DOWNLOAD_SELECTION", Message(content.result.strip()))


@rss_select_file_cmd.got(
    "DOWNLOAD_SELECTION",
    prompt="请输入：GID 文件编号\n例如：0123456789abcdef 1,3-5",
)
async def handle_select_files(
    bot: Bot,
    event: GroupMessageEvent,
    value: str = ArgPlainText("DOWNLOAD_SELECTION"),
) -> None:
    parts = value.strip().split(maxsplit=1)
    if len(parts) != 2:
        await rss_select_file_cmd.reject(
            "格式错误，请输入：GID 文件编号\n例如：0123456789abcdef 1,3-5"
        )
        return

    gid, selection = parts
    if not re.fullmatch(r"[0-9a-fA-F]{16}", gid):
        await rss_select_file_cmd.reject("GID 格式错误，请输入 16 位十六进制 GID")
        return

    try:
        result = await select_download_files(
            bot=bot,
            gid=gid,
            selection=selection,
            group_ids=[str(event.group_id)],
        )
    except DownloadSizeLimitExceeded as exc:
        await rss_select_file_cmd.finish(f"❌ 已拒绝下载：\n{exc}")
        return
    except Aria2Error as exc:
        await rss_select_file_cmd.reject(f"❌ 选择文件失败：{exc}")
        return

    await rss_select_file_cmd.finish(
        f"已选择 {result['selected_count']} 个文件并开始下载。\n"
        f"{result['summary']}"
    )


@rss_close_cmd.handle()
async def prepare_close_download(matcher: Matcher, content: AlcMatch[str]) -> None:
    if content.available and content.result.strip():
        matcher.set_arg("DOWNLOAD_GID", Message(content.result.strip()))


@rss_close_cmd.got("DOWNLOAD_GID", prompt="请输入要终止的下载任务 GID")
async def handle_close_download(
    gid: str = ArgPlainText("DOWNLOAD_GID"),
) -> None:
    gid = gid.strip()
    if not re.fullmatch(r"[0-9a-fA-F]{16}", gid):
        await rss_close_cmd.reject("GID 格式错误，请输入 16 位十六进制 GID")
        return

    try:
        previous_status = await cancel_download(gid)
    except Aria2Error as exc:
        await rss_close_cmd.finish(f"❌ 终止下载任务失败：{exc}")
        return

    if previous_status == "complete":
        await rss_close_cmd.finish(f"任务 {gid} 已经下载完成，已清理任务记录。")
    await rss_close_cmd.finish(
        f"已终止下载任务：{gid}\n已下载到磁盘的部分文件不会自动删除。"
    )


@rss_retry_upload_cmd.handle()
async def prepare_retry_upload(matcher: Matcher, content: AlcMatch[str]) -> None:
    if content.available and content.result.strip():
        matcher.set_arg("UPLOAD_RETRY_GID", Message(content.result.strip()))


@rss_retry_upload_cmd.got(
    "UPLOAD_RETRY_GID", prompt="请输入要重试上传的任务 GID"
)
async def handle_retry_upload(
    bot: Bot,
    event: GroupMessageEvent,
    gid: str = ArgPlainText("UPLOAD_RETRY_GID"),
) -> None:
    gid = gid.strip()
    if not re.fullmatch(r"[0-9a-fA-F]{16}", gid):
        await rss_retry_upload_cmd.reject("GID 格式错误，请输入 16 位十六进制 GID")
        return

    try:
        succeeded = await retry_upload_to_group(bot, gid, str(event.group_id))
    except Aria2Error as exc:
        await rss_retry_upload_cmd.finish(f"❌ 重试上传失败：{exc}")
        return

    if not succeeded:
        await rss_retry_upload_cmd.finish()
        return
    await rss_retry_upload_cmd.finish(
        f"✅ GID：{gid}\n当前群待重试的文件已上传完成。"
    )


@rss_delete_file_cmd.handle()
async def prepare_delete_files(matcher: Matcher, content: AlcMatch[str]) -> None:
    if content.available and content.result.strip():
        matcher.set_arg("DELETE_FILE_GID", Message(content.result.strip()))


@rss_delete_file_cmd.got(
    "DELETE_FILE_GID", prompt="请输入要删除下载文件的任务 GID"
)
async def handle_delete_files(
    gid: str = ArgPlainText("DELETE_FILE_GID"),
) -> None:
    gid = gid.strip()
    if not re.fullmatch(r"[0-9a-fA-F]{16}", gid):
        await rss_delete_file_cmd.reject("GID 格式错误，请输入 16 位十六进制 GID")
        return

    try:
        deleted_count, failed_paths = await delete_download_files(gid)
    except Aria2Error as exc:
        await rss_delete_file_cmd.finish(f"❌ 删除下载文件失败：{exc}")
        return

    if failed_paths:
        details = "\n".join(f"- {path}" for path in failed_paths)
        await rss_delete_file_cmd.finish(
            f"⚠️ GID：{gid}\n已删除 {deleted_count} 个文件，"
            f"以下文件删除失败：\n{details}\n"
            "任务记录已保留，可以稍后再次执行删除文件指令。"
        )
        return
    await rss_delete_file_cmd.finish(
        f"✅ GID：{gid}\n已删除 {deleted_count} 个下载文件并清理任务记录。"
    )
