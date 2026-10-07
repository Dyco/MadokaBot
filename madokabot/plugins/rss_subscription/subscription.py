import re
from copy import deepcopy
from enum import Enum
from pathlib import Path
from shutil import copy2
from typing import Any, Dict, List, Optional

from tinydb import Query, TinyDB
from tinydb.operations import set as tinydb_set
from yarl import URL

from .config import (
    DATA_PATH,
    JSON_PATH,
    LEGACY_DATA_PATH,
    LEGACY_JSON_PATH,
    config,
)


class DuplicateFilterMode(str, Enum):
    LINK = "link"
    TITLE = "title"
    IMAGE = "image"
    OR = "or"


DUPLICATE_FILTER_VALUES = {mode.value for mode in DuplicateFilterMode}


class Rss:
    def __init__(self, data: Optional[Dict[str, Any]] = None):
        self.name: str = ""
        self.url: str = ""
        self.user_id: List[str] = []
        self.group_id: List[str] = []
        self.guild_channel_id: List[str] = []
        self.img_proxy: bool = False
        self.time: str = "5"
        self.only_title: bool = False
        self.only_pic: bool = False
        self.only_has_pic: bool = False
        self.download_pic: bool = False
        self.cookies: str = ""
        self.down_torrent: bool = False
        self.down_torrent_keyword: str = ""
        self.black_keyword: str = ""
        self.is_open_upload_group: bool = True
        self.duplicate_filter_mode: List[str] = []
        self.max_image_number: int = 0
        self.content_to_remove: Optional[List[str]] = None
        self.etag: Optional[str] = None
        self.last_modified: Optional[str] = None
        self.error_count: int = 0
        self.stop: bool = False
        self.send_forward_msg: bool = (
            False
        )
        if data:
            # 忽略模型之外的旧字段。
            known_fields = set(self.__dict__)
            self.__dict__.update(
                {
                    key: value
                    for key, value in data.items()
                    if key in known_fields
                }
            )
            self.user_id = self._normalize_string_list(self.user_id)
            self.group_id = self._normalize_string_list(self.group_id)
            self.guild_channel_id = self._normalize_string_list(self.guild_channel_id)
            self.duplicate_filter_mode = [
                mode
                for mode in self._normalize_string_list(self.duplicate_filter_mode)
                if mode in DUPLICATE_FILTER_VALUES
            ]
            if isinstance(self.content_to_remove, str):
                self.content_to_remove = (
                    [self.content_to_remove] if self.content_to_remove else None
                )
            elif self.content_to_remove:
                self.content_to_remove = self._normalize_string_list(
                    self.content_to_remove
                )
            else:
                self.content_to_remove = None

    @staticmethod
    def _normalize_string_list(value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, str):
            value = value.split(",")
        if not isinstance(value, (list, tuple, set)):
            value = [value]
        return [str(item).strip() for item in value if str(item).strip()]

    @staticmethod
    def _migrate_legacy_data() -> None:
        """RSS旧数据迁移方法。"""
        if JSON_PATH.exists() or not LEGACY_JSON_PATH.exists():
            return

        DATA_PATH.mkdir(parents=True, exist_ok=True)
        copy2(LEGACY_JSON_PATH, JSON_PATH)
        for source in LEGACY_DATA_PATH.glob("*.json"):
            target = DATA_PATH / source.name
            if not target.exists():
                copy2(source, target)
        legacy_cache = LEGACY_DATA_PATH / "cache.db"
        target_cache = DATA_PATH / "cache.db"
        if legacy_cache.exists() and not target_cache.exists():
            copy2(legacy_cache, target_cache)

    def get_url(self, rsshub: str = str(config.rsshub)) -> str:
        if URL(self.url).scheme in ["http", "https"]:
            return self.url
        return f"{rsshub.rstrip('/')}/{self.url.lstrip('/')}"

    @staticmethod
    def read_rss() -> List["Rss"]:
        Rss._migrate_legacy_data()
        if not JSON_PATH.exists():
            return []
        with TinyDB(
            JSON_PATH,
            encoding="utf-8",
            sort_keys=True,
            indent=4,
            ensure_ascii=False,
        ) as db:
            rss_list = [Rss(rss) for rss in db.all()]
        return rss_list

    @staticmethod
    def handle_name(name: str) -> str:
        name = re.sub(r'[?*:"<>\\/|]', "_", name)
        if name == "rss":
            name = "rss_"
        return name

    @staticmethod
    def get_one_by_name(name: str) -> Optional["Rss"]:
        feed_list = Rss.read_rss()
        return next((feed for feed in feed_list if feed.name == name), None)

    @staticmethod
    def normalize_url(url: str) -> str:
        """订阅地址规范化方法。"""
        rss = Rss()
        rss.url = url.strip()
        parsed = URL(rss.get_url()).with_fragment(None)
        path = parsed.path.rstrip("/") or "/"
        query = list(parsed.query.items())
        if (
            parsed.host == "danbooru.donmai.us"
            and path in {"/posts", "/posts.atom", "/posts.json"}
        ):
            path = "/posts"
            query = [(key, value) for key, value in query if key != "format"]
        query.sort()
        return str(parsed.with_path(path).with_query(query))

    @staticmethod
    def get_one_by_url(url: str) -> Optional["Rss"]:
        normalized_url = Rss.normalize_url(url)
        return next(
            (
                rss
                for rss in Rss.read_rss()
                if Rss.normalize_url(rss.url) == normalized_url
            ),
            None,
        )

    def add_user_or_group_or_channel(
        self,
        user: Optional[str] = None,
        group: Optional[str] = None,
        guild_channel: Optional[str] = None,
    ) -> None:
        if user:
            if user in self.user_id:
                return
            self.user_id.append(user)
        elif group:
            if group in self.group_id:
                return
            self.group_id.append(group)
        elif guild_channel:
            if guild_channel in self.guild_channel_id:
                return
            self.guild_channel_id.append(guild_channel)
        self.upsert()

    def delete_group(self, group: str) -> bool:
        if group not in self.group_id:
            return False
        self.group_id.remove(group)
        with TinyDB(
            JSON_PATH,
            encoding="utf-8",
            sort_keys=True,
            indent=4,
            ensure_ascii=False,
        ) as db:
            db.update(tinydb_set("group_id", self.group_id), Query().name == self.name)  # type: ignore
        return True

    def delete_guild_channel(self, guild_channel: str) -> bool:
        if guild_channel not in self.guild_channel_id:
            return False
        self.guild_channel_id.remove(guild_channel)
        with TinyDB(
            JSON_PATH,
            encoding="utf-8",
            sort_keys=True,
            indent=4,
            ensure_ascii=False,
        ) as db:
            db.update(
                tinydb_set("guild_channel_id", self.guild_channel_id), Query().name == self.name  # type: ignore
            )
        return True

    def delete_rss(self) -> None:
        with TinyDB(
            JSON_PATH,
            encoding="utf-8",
            sort_keys=True,
            indent=4,
            ensure_ascii=False,
        ) as db:
            db.remove(Query().name == self.name)
        self.delete_file()

    def rename_file(self, target: str) -> None:
        source = DATA_PATH / f"{Rss.handle_name(self.name)}.json"
        if source.exists():
            Path(target).parent.mkdir(parents=True, exist_ok=True)
            source.rename(target)

    def delete_file(self) -> None:
        (DATA_PATH / f"{Rss.handle_name(self.name)}.json").unlink(missing_ok=True)

    def hide_some_infos(
        self, group_id: Optional[int] = None, guild_channel_id: Optional[str] = None
    ) -> "Rss":
        if not group_id and not guild_channel_id:
            return self
        rss_tmp = deepcopy(self)
        rss_tmp.guild_channel_id = [guild_channel_id, "*"] if guild_channel_id else []
        rss_tmp.group_id = [str(group_id), "*"] if group_id else []
        rss_tmp.user_id = ["*"] if rss_tmp.user_id else []
        return rss_tmp

    @staticmethod
    def get_by_guild_channel(guild_channel_id: str) -> List["Rss"]:
        rss_old = Rss.read_rss()
        return [
            rss.hide_some_infos(guild_channel_id=guild_channel_id)
            for rss in rss_old
            if guild_channel_id in rss.guild_channel_id
        ]

    @staticmethod
    def get_by_group(group_id: int) -> List["Rss"]:
        rss_old = Rss.read_rss()
        return [
            rss.hide_some_infos(group_id=group_id)
            for rss in rss_old
            if str(group_id) in rss.group_id
        ]

    @staticmethod
    def get_by_user(user: str) -> List["Rss"]:
        rss_old = Rss.read_rss()
        return [rss for rss in rss_old if user in rss.user_id]

    def set_cookies(self, cookies: str) -> None:
        self.cookies = cookies
        with TinyDB(
            JSON_PATH,
            encoding="utf-8",
            sort_keys=True,
            indent=4,
            ensure_ascii=False,
        ) as db:
            db.update(tinydb_set("cookies", cookies), Query().name == self.name)  # type: ignore

    def upsert(self, old_name: Optional[str] = None) -> None:
        with TinyDB(
            JSON_PATH,
            encoding="utf-8",
            sort_keys=True,
            indent=4,
            ensure_ascii=False,
        ) as db:
            if old_name:
                db.update(self.__dict__, Query().name == old_name)
            else:
                db.upsert(self.__dict__, Query().name == str(self.name))

    def __str__(self) -> str:
        def _generate_feature_string(feature: str, value: Any) -> str:
            return f"{feature}：{value}" if value else ""

        if self.duplicate_filter_mode:
            delimiter = " 或 " if "or" in self.duplicate_filter_mode else "、"
            mode_name = {
                DuplicateFilterMode.LINK.value: "链接",
                DuplicateFilterMode.TITLE.value: "标题",
                DuplicateFilterMode.IMAGE.value: "图片",
            }
            mode_msg = (
                "已启用去重模式，"
                f"{delimiter.join(mode_name[i] for i in self.duplicate_filter_mode if i != 'or')} 相同时去重"
            )
        else:
            mode_msg = ""

        ret_list = [
            f"名称：{self.name}",
            f"订阅地址：{self.url}",
            _generate_feature_string("订阅QQ", self.user_id),
            _generate_feature_string("订阅群", self.group_id),
            _generate_feature_string("订阅子频道", self.guild_channel_id),
            f"更新时间：{self.time}",
            _generate_feature_string("代理", self.img_proxy),
            _generate_feature_string("仅标题", self.only_title),
            _generate_feature_string("仅图片", self.only_pic),
            _generate_feature_string("下载图片", self.download_pic),
            _generate_feature_string("仅含有图片", self.only_has_pic),
            _generate_feature_string("白名单关键词", self.down_torrent_keyword),
            _generate_feature_string("黑名单关键词", self.black_keyword),
            _generate_feature_string("cookies", self.cookies),
            "种子自动下载功能已启用" if self.down_torrent else "",
            (
                ""
                if self.is_open_upload_group
                else f"是否上传到群：{self.is_open_upload_group}"
            ),
            mode_msg,
            _generate_feature_string("图片数量限制", self.max_image_number),
            _generate_feature_string("正文待移除内容", self.content_to_remove),
            _generate_feature_string("连续抓取失败的次数", self.error_count),
            _generate_feature_string("停止更新", self.stop),
        ]
        return "\n".join([i for i in ret_list if i != ""])
