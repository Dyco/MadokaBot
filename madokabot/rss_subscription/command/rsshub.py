from typing import Any, Dict

import aiohttp
from nonebot.adapters.onebot.v11 import Message, MessageEvent
from nonebot.matcher import Matcher
from nonebot.params import ArgPlainText
from nonebot.typing import T_State
from nonebot_plugin_alconna import Match as AlcMatch
from yarl import URL

from ..config import config
from ..subscription import Rss
from ..utils import get_proxy
from .matchers import rsshub_cmd
from .add import add_feed

rsshub_routes: Dict[str, Any] = {}


@rsshub_cmd.handle()
async def prepare_rsshub_add(matcher: Matcher, content: AlcMatch[str]) -> None:
    if content.available and content.result.strip():
        matcher.set_arg("route", Message(content.result))


@rsshub_cmd.got("name", prompt="请输入要订阅的订阅名")
async def handle_feed_name(name: str = ArgPlainText("name")) -> None:
    if not name.strip():
        await rsshub_cmd.reject("订阅名不能为空，请重新输入")
        return

    if Rss.get_one_by_name(name=name):
        await rsshub_cmd.reject(f"已存在名为 {name} 的订阅，请重新输入")


@rsshub_cmd.got("route", prompt="请输入要订阅的 RSSHub 路由名")
async def handle_rsshub_routes(
    state: T_State, route: str = ArgPlainText("route")
) -> None:
    if not route.strip():
        await rsshub_cmd.reject("路由名不能为空，请重新输入")
        return

    rsshub_url = URL(str(config.rsshub))
    # 对本机部署的 RSSHub 不使用代理
    local_host = [
        "localhost",
        "127.0.0.1",
    ]
    if get_proxy() and rsshub_url.host not in local_host:
        proxy = get_proxy()
    else:
        proxy = None

    global rsshub_routes
    if not rsshub_routes:
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15)
            ) as session:
                resp = await session.get(
                    rsshub_url.with_path("api/routes"), proxy=proxy
                )
                response_status = resp.status
                response_data = await resp.json()
        except Exception as e:
            await rsshub_cmd.finish(f"获取 RSSHub 路由失败：{e}")
        if response_status != 200:
            await rsshub_cmd.finish(
                "获取路由数据失败，请检查 RSSHub 的地址配置及网络连接"
            )
        rsshub_routes = response_data

    if route not in rsshub_routes["data"]:
        await rsshub_cmd.reject(f"未找到名为 {route} 的 RSSHub 路由，请重新输入")
    else:
        route_list = state["route_list"] = rsshub_routes["data"][route]["routes"]
        if len(route_list) > 1:
            await rsshub_cmd.send(
                "请输入序号来选择要订阅的 RSSHub 路由：\n"
                + "\n".join(
                    f"{index + 1}. {_route}" for index, _route in enumerate(route_list)
                )
            )
        else:
            state["route_index"] = Message("1")


@rsshub_cmd.got("route_index")
async def handle_route_index(
    state: T_State, route_index: str = ArgPlainText("route_index")
) -> None:
    try:
        route_number = int(route_index)
        route = state["route_list"][route_number - 1]
    except (KeyError, ValueError, IndexError):
        await rsshub_cmd.reject("路由序号无效，请重新输入")
        return
    if args := [i for i in route.split("/") if i.startswith(":")]:
        await rsshub_cmd.send(
            '请依次输入要订阅的 RSSHub 路由参数，并用 "/" 分隔：\n'
            + "/".join(
                f"{i.rstrip('?')}(可选)" if i.endswith("?") else f"{i}" for i in args
            )
            + "\n要置空请输入#或直接留空"
        )
    else:
        state["route_args"] = Message()


@rsshub_cmd.got("route_args")
async def handle_route_args(
    event: MessageEvent,
    state: T_State,
    name: str = ArgPlainText("name"),
    route_index: str = ArgPlainText("route_index"),
    route_args: str = ArgPlainText("route_args"),
) -> None:
    try:
        route_number = int(route_index)
        route = state["route_list"][route_number - 1]
    except (KeyError, ValueError, IndexError):
        await rsshub_cmd.finish("路由序号无效，请重新开始添加订阅")
        return
    feed_url = "/".join([i for i in route.split("/") if not i.startswith(":")])
    for i in route_args.split("/"):
        if len(i.strip("#")) > 0:
            feed_url += f"/{i}"

    await add_feed(name, feed_url.lstrip("/"), event, matcher=rsshub_cmd)
