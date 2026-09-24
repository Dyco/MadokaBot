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

## 入群提示

机器人加入非白名单群时，发送“此群聊不在白名单中，指令无法使用，请联系事务所负责人（机器人创建者）”。
人数低于 `auto_leave_group_min_members`（默认 5）或高于 `auto_leave_group_max_members`（默认 200）时，另行提示人数“过少”或“过多”，将在 3 分钟后自动退群。
到期前加入白名单，或复核时人数已符合范围，则取消退群。白名单群与其他成员入群不触发这些提示。


## 内置功能

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

## 扩展插件

cs_match_subscription
支持5E与完美平台对战战绩查询，以及HLTV赛事相关解析
此插件需要使用FlareSolverr访问HLTV数据页

picture_maker
制图系列指令，一键生成各种风格图片

## 引用插件

zhaomaoniu/nonebot-plugin-steam-info
steam插件，查询好友在线状态，推送好友游戏上线/离线消息
此插件针对MadokaBot进行特殊适配

zhiyu1998/nonebot-plugin-resolver
解析插件，支持Bilibili、抖音、TikTok、ACFun、X、小红书、YouTube、网易云、酷狗和微博链接。
此插件针对MadokaBot进行特殊适配

Quan666/ELF_RSS
RSS/RSSHub动态订阅、更新推送、图片处理、去重及可选aria2种子下载上传
此插件针对MadokaBot进行特殊适配
