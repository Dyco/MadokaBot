import re
from dataclasses import dataclass
from inspect import signature
from typing import Any, Callable, Dict, List, Optional, Tuple

from tinydb import TinyDB

from .config import DATA_PATH
from .subscription import Rss
from .utils import partition_list


@dataclass(frozen=True)
class HandlerSpec:
    """One handler registered for matching subscription URLs."""

    func: Callable[..., Any]
    rex: str = "(.*)"
    priority: int = 10
    block: bool = False


def _sort(handlers: List[HandlerSpec]) -> List[HandlerSpec]:
    return sorted(handlers, key=lambda handler: handler.priority)


class HandlerRegistry:
    """Registry for the default pipeline and route-specific overrides."""

    before_handler: List[HandlerSpec] = []
    handler: Dict[str, List[HandlerSpec]] = {
        "title": [],
        "summary": [],
        "picture": [],
        "source": [],
        "date": [],
        "torrent": [],
        "after": [],
    }
    after_handler: List[HandlerSpec] = []

    @classmethod
    def append_handler(
        cls,
        parsing_type: str,
        rex: str = "(.*)",
        priority: int = 10,
        block: bool = False,
    ) -> Callable[..., Any]:
        def _decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            cls.handler[parsing_type].append(HandlerSpec(func, rex, priority, block))
            cls.handler[parsing_type] = _sort(cls.handler[parsing_type])
            return func

        return _decorator

    @classmethod
    def append_before_handler(
        cls, rex: str = "(.*)", priority: int = 10, block: bool = False
    ) -> Callable[..., Any]:
        """Register a handler that runs before individual entries."""

        def _decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            cls.before_handler.append(HandlerSpec(func, rex, priority, block))
            cls.before_handler = _sort(cls.before_handler)
            return func

        return _decorator

    @classmethod
    def append_after_handler(
        cls, rex: str = "(.*)", priority: int = 10, block: bool = False
    ) -> Callable[..., Any]:
        """Register a handler that runs after an entry batch."""

        def _decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            cls.after_handler.append(HandlerSpec(func, rex, priority, block))
            cls.after_handler = _sort(cls.after_handler)
            return func

        return _decorator


def _handler_filter(
    handlers: List[HandlerSpec], url: str
) -> List[HandlerSpec]:
    matched = [handler for handler in handlers if re.search(handler.rex, url)]
    overridden_defaults = [
        (handler.func.__name__, "(.*)", handler.priority)
        for handler in matched
        if handler.rex != "(.*)"
    ]
    return [
        handler
        for handler in matched
        if (handler.func.__name__, handler.rex, handler.priority)
        not in overridden_defaults
    ]


async def _run_handlers(
    handlers: List[HandlerSpec],
    rss: Rss,
    state: Dict[str, Any],
    item: Optional[Dict[str, Any]] = None,
    item_msg: Optional[str] = None,
    tmp: Optional[str] = None,
    tmp_state: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], str]:
    for handler in handlers:
        kwargs = {
            "rss": rss,
            "state": state,
            "item": item,
            "item_msg": item_msg,
            "tmp": tmp,
            "tmp_state": tmp_state,
        }
        handler_params = signature(handler.func).parameters
        handler_kwargs = {k: v for k, v in kwargs.items() if k in handler_params}

        if item is not None:
            tmp = await handler.func(**handler_kwargs)
        else:
            state.update(await handler.func(**handler_kwargs))
        if handler.block or (tmp_state is not None and not tmp_state.get("continue")):
            break
    return state, tmp or ""


class FeedProcessor:
    """Run the registered processing pipeline for one subscription feed."""

    def __init__(self, rss: Rss):
        self.state: Dict[str, Any] = {}
        self.rss: Rss = rss

        self.before_handler: List[HandlerSpec] = _handler_filter(
            HandlerRegistry.before_handler, self.rss.get_url()
        )
        self.handler: Dict[str, List[HandlerSpec]] = {}
        for k, v in HandlerRegistry.handler.items():
            self.handler[k] = _handler_filter(v, self.rss.get_url())
        self.after_handler: List[HandlerSpec] = _handler_filter(
            HandlerRegistry.after_handler, self.rss.get_url()
        )

    async def start(self, rss_name: str, new_rss: Dict[str, Any]) -> None:
        rss_title = new_rss["feed"]["title"]
        new_data = new_rss["entries"]
        _file = DATA_PATH / f"{Rss.handle_name(rss_name)}.json"
        db = TinyDB(
            _file,
            encoding="utf-8",
            sort_keys=True,
            indent=4,
            ensure_ascii=False,
        )
        self.state.update(
            {
                "rss_title": rss_title,
                "new_data": new_data,
                "change_data": [],
                "conn": None,
                "tinydb": db,
                "error_count": 0,
            }
        )
        self.state, _ = await _run_handlers(self.before_handler, self.rss, self.state)

        self.state.update(
            {
                "header_message": f"【{rss_title}】更新了!",
                "messages": [],
                "items": [],
            }
        )
        if change_data := self.state["change_data"]:
            batches = list(partition_list(change_data, 10))
            for batch_index, parted_item_list in enumerate(batches):
                for item in parted_item_list:
                    item_msg = ""
                    for handler_list in self.handler.values():
                        tmp = ""
                        tmp_state = {"continue": True}

                        _, tmp = await _run_handlers(
                            handler_list,
                            self.rss,
                            self.state,
                            item=item,
                            item_msg=item_msg,
                            tmp=tmp,
                            tmp_state=tmp_state,
                        )
                        item_msg += tmp
                    self.state["messages"].append(item_msg)
                    self.state["items"].append(item)

                self.state["is_last_batch"] = batch_index == len(batches) - 1
                _, _ = await _run_handlers(self.after_handler, self.rss, self.state)
                self.state["messages"] = []
                self.state["items"] = []
        else:
            self.state["is_last_batch"] = True
            _, _ = await _run_handlers(self.after_handler, self.rss, self.state)
