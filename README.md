# MadokaBot

樋口円香机器人，正在开发中…
当前版本 Ver.0.3.0

## 项目结构

```text
madokabot/
├── bootstrap.py                 # 公共依赖、数据库初始化与插件加载入口
├── core/                        # 跨功能共享的支持模块
│   ├── config.py                # 全局配置
│   ├── db/                      # 共享模型基类、元数据与建表入口
│   ├── files/                   # 缓存文件清理
│   ├── group/                   # 群设置、白名单与黑名单存储
│   ├── messaging/               # 资源消息、消息回应、媒体发送、管理员通知与分页工具
│   ├── resources/               # 资源目录、类型枚举、文件检索与索引
│   ├── storage/                 # JSON 存储支持
│   ├── user/                    # 共享用户数据、签到统计、账号查询和旧表兼容
│   └── version.py               # 包版本读取
├── default/                     # 默认业务功能
│   ├── account/                 # 注册、资料查询、立绘设置及用户卡片
│   ├── chat/                    # 聊天命令、处理器、模型客户端与角色提示词
│   ├── copying/                 # 复读插件，主命令固定为 copying
│   ├── greeting/
│   ├── group/                   # 群名单管理与自动退群
│   ├── help/                    # 帮助入口
│   ├── ping/
│   ├── poke/
│   ├── shop/                    # 库存模型、立绘目录、购买服务、指令与卡片
│   └── sign/                    # 签到命令、会话处理与奖励服务
└── plugins/                     # 扩展业务插件
    ├── cs_match_subscription/   # commands 指令、players 战绩、subscriptions 赛事订阅
    ├── link_resolver/         # 自动解析、平台处理器和接口源、插件专用下载
    ├── picture_maker/
    ├── rss_subscription/       # 下载编排、种子源文件、清理、记录与群文件上传
    └── steam/                   # 命令、共享状态、客户端、绘图与定时播报
```

`default` 与 `plugins` 属于同一业务层，公共能力统一从 `core` 导入。
`core` 不引用业务插件，扩展插件不依赖默认功能。跨层使用绝对导入，模块内部可以使用相对导入。

NoneBot 通过 `pyproject.toml` 中的 `madokabot.bootstrap` 加载项目；入口先声明公共依赖，再分别加载 `default` 和 `plugins`。
公共目录和模板目录不作为独立插件扫描。新增业务插件应在对应目录下创建包，并在其 `__init__.py` 中定义插件元数据、显式导入处理器完成注册。

目录和模块使用含义明确的 `snake_case` 名称，例如 `cs_match_subscription`；命令处理目录统一使用 `commands`，模板目录使用 `templates`。
复读插件约定命名为 `copying`，主命令保持 `copying`，保留“复读”和“复读机”别名。
业务专用绘图代码随业务保存，不以 Pillow 等底层库名作为插件名。

`common` 已按账号、商店、群管理和帮助职责拆分。签到复用账号注册服务及用户卡片，群管理和商店通过公共分页工具交互。
聊天命令定义与消息处理分别放在 `chat/matchers.py` 和 `chat/handlers.py`，模型请求与候选模型切换归 `chat/client.py`，角色提示词归 `chat/prompts.py`。签到同样由 `matchers.py`、`handlers.py` 和 `service.py` 分别负责命令、会话与奖励；两个插件入口仅保留元数据和加载声明。
Steam 入口仅声明元数据并加载命令、定时任务；`commands` 按绑定、查询、设置分组，`state.py` 集中保存共享数据实例和查询冷却，`monitor.py` 负责状态更新与播报，`scheduler.py` 注册轮询任务。原 `steam.py`、`draw.py`、`data_source.py` 分别规范为 `client.py`、`render.py`、`storage.py`。Steam 数据统一使用下述新存储结构。
资源目录、枚举、检索和运行时编号统一从 `core/resources` 导入；该模块不依赖消息适配器。资源转 OneBot 消息段及随机资源消息放在 `core/messaging/resources.py`，版本读取放在 `core/version.py`，Ping 延迟计算归 Ping 插件自身；不再保留混合职责的 `core/utils.py`。
`core/db` 仅提供共享模型基类和建表能力，不导入业务模型。`core/user` 保存跨功能共享的账号资料、积分、签到统计及查询接口；签到记录同时被注册、资料卡和积分榜使用，因此保留在共享用户领域。
商店库存模型、立绘目录和购买服务归 `default/shop`；CS 竞猜模型归 `plugins/cs_match_subscription/prediction_models.py`。
CS 玩家战绩归 `plugins/cs_match_subscription/players`：`service.py` 编排绑定和查询，`storage.py` 管理玩家绑定，`five_e.py` 与 `perfect_world.py` 分别调用平台接口，`session.py` 保存完美登录会话，`http.py` 统一请求和重试，`views` 按平台生成卡片数据。原 `player_stats.py` 已移除，命令直接调用对应模块；模板字段、绑定数据库及会话路径保持原有约定。
CS 的 `matchers.py` 仅定义指令和用法，`commands` 按查询、玩家、设置、订阅、竞猜分组，群权限检查集中在 `commands/permissions.py`。`subscriptions` 分离通知生成、消息发送、状态判断、去重记忆、Rating 卡片、单场比赛处理与赛事轮询，替代原根目录 `service.py`；两个定时任务由 `scheduler.py` 注册，沿用原任务 ID、周期与并发限制。
RSS 的 `aria2_client.py` 负责 JSON-RPC、种子获取与任务提交，`download_validation.py` 负责文件选择及大小限制，`download_state.py` 保存进程内任务状态，`download_records.py` 负责原有 JSON 路径的记录读写与上传项整理。`download_details.py` 和 `download_notices.py` 提供下载状态摘要与群通知；`torrent_sources.py`、`download_cleanup.py` 和 `download_progress.py` 分别管理种子源文件、本地清理和进度消息。`download.py` 编排任务启动、文件选择和轮询，`uploads` 分离上传队列、完成收尾、延迟核验、手动重试和重启恢复。命令与启动入口直接从对应模块导入，原任务 ID、上传并发配置和记录路径保持不变。
链接解析的 `handlers.py` 按原顺序加载 `platforms` 下十个平台处理器；平台共享配置、代理选择及视频时长判断分别归 `runtime.py`、`video.py`。平台接口请求、数据解析和专用下载归插件的 `sources` 目录，评论获取与渲染归 `comments.py`，媒体缓存与下载归插件的 `downloads.py`。自动解析 matcher 继续作为事件监听注册，通用媒体发送使用公共 `core/messaging/media.py`。抖音签名脚本随 `sources/tiktok.py` 保存；媒体和评论缓存继续使用原 Localstore 路径。
各模块加载时注册自身模型，数据库就绪后由 `bootstrap` 统一建表，再执行用户旧表字段兼容。所有模型继续共用原有元数据和数据命名空间。
单纯目录重命名不改变数据库表名、数据命名空间、资源目录、群设置键、环境配置项或现有命令。例如 `madoka_bundle`、`madokabot_cs_match_subscribe`、`group_set.json` 和 `copying_number` 仍用于兼容已有数据与配置。Steam 的数据存储另行改为新结构，不兼容或迁移其旧数据。

群名单分页改用 `group_session_timeout`，未配置时兼容之前共用的 `shop_session_timeout`；商店继续使用原配置项。

## Steam 数据存储

群内绑定、昵称备注、播报开关和群名通过公共 `GroupSettingsStore` 保存到 `assets_path/json/group/group_set.json` 中各群的 `steam` 节点，不影响同群的其他插件设置：

```json
{
  "123456": {
    "steam": {
      "bindings": [
        {"user_id": "654321", "steam_id": "76561197960265729", "nickname": null}
      ],
      "broadcast_enabled": true,
      "group_name": "群名称"
    }
  }
}
```

播报默认启用，群名和绑定按使用情况写入。同一 Steam 账号可以用于不同群，但不能被同群不同成员重复绑定。
跨群共享的玩家在线状态通过公共资源目录方法和 `JsonDataStore` 单独保存到 `assets_path/json/steam/player_status.json`，以 Steam ID 为键；状态轮询不会反复写入群配置。
群头像和玩家头像使用 Localstore 公共缓存目录接口，分别保存于 `madokabot_steam/group_avatars` 和 `madokabot_steam/player_avatars`。
不再读取、写入或迁移旧的 `bind_data.json`、`parent_data.json`、`disable_parent_data.json`、`steam_info.json`；使用新版本后重新绑定和设置即可。

## 后续整理清单

顶层目录归位已经完成：10 个默认功能、5 个扩展插件。默认功能和公共数据、资源支持已按职责整理；简单的 Ping、戳一戳、问候和帮助入口保留紧凑结构。
Steam、CS、RSS、链接解析和公共媒体的主要职责拆分已完成。公共媒体由 `media_files.py` 检查文件与大小，`media_ffmpeg.py` 负责视频探测和转码，`media_onebot.py` 负责视频暂存、OneBot 消息及群文件接口；`media.py` 保留原有 `MediaDelivery` 使用入口与缓存常量。后续可按实际运行问题继续细化业务模块。

## 命令起始符约定

除 `on_message(rule=fullmatch(...))` 定义的完整匹配指令外，业务命令必须使用 NoneBot 的全局 `COMMAND_START`。
所有 `on_alconna` 注册均显式设置 `use_cmd_start=True`，不得设为 `False`，也不得在别名中硬编码起始符。
例如配置 `COMMAND_START=["/"]` 后，复读控制使用 `/copying on`，扩展命令使用 `/RSS 帮助`、`/CS help`、`/制图 音乐 ...`。
注册、签到、Ping 和裸“帮助”保持完整匹配行为；自动复读、链接自动解析及通知事件不属于指令，不受此约定限制。

## 账号改名

使用 `/set rename <名字>`，子命令别名为“改名”“更名”，例如 `/设置 改名 天泽神月`。
去除首尾空白后，名字长度须为 1～10 个字符或汉字，每次成功改名消耗 10 积分；余额不足或名字不合法时，不改名、不扣分。
账号显示名用于签到卡、资料卡和排行榜，不影响 QQ 昵称，后续签到也不会覆盖它。起始符遵循全局配置。

## 入群提示

机器人加入非白名单群时，发送“此群聊不在白名单中，指令无法使用，请联系事务所负责人（机器人创建者）”。
人数低于 `auto_leave_group_min_members`（默认 5）或高于 `auto_leave_group_max_members`（默认 200）时，另行提示人数“过少”或“过多”，将在 3 分钟后自动退群。
到期前加入白名单，或复核时人数已符合范围，则取消退群。白名单群与其他成员入群不触发这些提示。


# 内置功能

账号、商店、群管理和帮助
按业务职责独立加载，包含注册、设置、查询、购买及群访问名单管理

卡片绘图
用于签到、用户资料和商店展示，由对应业务模块调用

回应
输入Ping快速测试机器人状态

签到
签到插件

制图
使用模板生成图片

戳戳
戳一戳回应语音消息

# 扩展插件

cs_match_subscription
支持5E与完美平台对战战绩查询，以及HLTV赛事相关解析
此插件需要使用FlareSolverr访问HLTV数据页

# 引用插件

zhaomaoniu/nonebot-plugin-steam-info
steam插件，查询好友在线状态，推送好友游戏上线/离线消息
此插件针对MadokaBot进行特殊适配

zhiyu1998/nonebot-plugin-resolver
解析插件，支持Bilibili、抖音、TikTok、ACFun、X、小红书、YouTube、网易云、酷狗和微博链接。
此插件针对MadokaBot进行特殊适配

Quan666/ELF_RSS
RSS/RSSHub动态订阅、更新推送、图片处理、去重及可选aria2种子下载上传
此插件针对MadokaBot进行特殊适配
