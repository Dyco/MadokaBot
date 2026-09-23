from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot.matcher import Matcher
from nonebot.params import ArgPlainText
from nonebot_plugin_alconna import Match as AlcMatch

from .. import scheduler
from ..subscription import Rss
from .matchers import rss_join_cmd


@rss_join_cmd.handle()
async def prepare_rss_join(matcher: Matcher, content: AlcMatch[str]) -> None:
    if content.available and content.result.strip():
        matcher.set_arg("RSS_JOIN", Message(content.result.strip()))


@rss_join_cmd.got("RSS_JOIN", prompt="请输入要加入的订阅名")
async def handle_rss_join(
    event: GroupMessageEvent,
    rss_name: str = ArgPlainText("RSS_JOIN"),
) -> None:
    rss_name = rss_name.strip()
    if not rss_name or any(character.isspace() for character in rss_name):
        await rss_join_cmd.reject("订阅名格式错误，请只输入一个订阅名")
        return

    rss = Rss.get_one_by_name(rss_name)
    if rss is None:
        await rss_join_cmd.finish(f"❌ 没有找到订阅：{rss_name}")
        return

    group_id = str(event.group_id)
    if group_id in rss.group_id:
        await rss_join_cmd.finish(f"当前群已经加入订阅：{rss.name}")
        return

    rss.add_user_or_group_or_channel(None, group_id, None)
    if not rss.stop:
        scheduler.delete_job(rss)
        scheduler.schedule_job(rss)

    result = f"👏 当前群已加入订阅：{rss.name}"
    if rss.stop:
        result += "\n⚠️ 该订阅目前处于停止状态，恢复更新后才会推送。"
    await rss_join_cmd.finish(result)
