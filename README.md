# MadokaBot

樋口円香机器人，正在开发中…
当前版本 Ver.0.3.0

## 浏览器环境与部署

图片渲染依赖 Playwright 的 Chromium。Docker 镜像在安装 Python 依赖后下载匹配的浏览器并安装系统依赖，服务器更新后在项目目录执行：

```bash
docker compose build nonebot
docker compose up -d nonebot
docker compose logs --tail=100 nonebot
```

非 Docker 部署需在机器人使用的 Python 环境中，以运行机器人的用户安装浏览器；Linux 系统依赖安装需要管理员权限：

```bash
python -m playwright install --with-deps chromium
```

出现 `Executable doesn't exist` 时，检查浏览器是否安装在相同用户、相同运行环境下。若安装失败，查看安装命令的完整输出；下载超时可设置 `PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT=120000` 后重试，无法访问下载地址时需配置可用的 `HTTPS_PROXY`。更新 Playwright 后需要重新安装匹配的浏览器。

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
│   ├── account/                 # 注册、资料查询、立绘与签到模板设置及用户卡片
│   ├── chat/                    # 聊天命令、处理器、模型客户端与角色提示词
│   ├── copying/                 # 复读插件，主命令固定为 copying
│   ├── greeting/
│   ├── group/                   # 群名单管理与自动退群
│   ├── help/                    # 帮助入口
│   ├── ping/
│   ├── poke/
│   ├── point/                   # 积分查询、转账、排名命令与事务服务
│   ├── shop/                    # 立绘与签到模板目录、库存、购买服务、指令与卡片
│   └── sign/                    # 签到命令、会话处理与奖励服务
└── plugins/                     # 扩展业务插件
    ├── cs_match_subscription/   # commands 指令、players 战绩、subscriptions 赛事订阅
    ├── link_resolver/         # 自动解析、平台处理器和接口源、插件专用下载
    ├── picture_maker/
    ├── rss_subscription/       # 下载编排、种子源文件、清理、记录与群文件上传
    └── steam/                   # 命令、共享状态、客户端、绘图与定时播报
```

## 群邀请与入群提示

收到邀请机器人入群的请求时，仅自动同意白名单中且不在黑名单中的群；白名单为空时不自动同意。其他邀请保留人工处理，不审批他人的入群申请。
自动审批使用 OneBot V11 标准接口，失败记录日志且不自动重试；接口调用成功仅表示已提交同意请求，实际入群以协议端通知为准。

机器人加入非白名单群时，发送“此群聊不在白名单中，指令无法使用，请联系事务所负责人（机器人创建者）”。
人数低于 `auto_leave_group_min_members`（默认 5）或高于 `auto_leave_group_max_members`（默认 200）时，另行提示人数“过少”或“过多”，将在 3 分钟后自动退群。
到期前加入白名单，或复核时人数已符合范围，则取消退群。白名单群与其他成员入群不触发这些提示。


## 内置功能

账号、商店、群管理和帮助
按业务职责独立加载，包含注册、设置、查询、购买及群访问名单管理

帮助菜单
发送 `help` / `帮助`，或带全局命令起始符的帮助指令，以合并转发查看分类总览及每个插件的名称、描述和用法；群聊和私聊均支持。
菜单只收集已加载且声明 `PluginMetadata.extra["help_category"]` 的插件，分类为 `响应内容`、`基础功能`、`拓展功能`。
同一分类按 `extra["help_order"]` 升序排列，未填写时使用 100，同序按插件显示名称排序。
插件详情直接使用 `name`、`description`、`usage`；新增展示内容只需维护该插件的元数据，加载入口、管理后台和启动问候不加入菜单。
版本号读取项目包版本，指令仍遵循全局 `COMMAND_START`，完整匹配关键词除外。

卡片绘图
用于签到、用户资料和商店展示，由对应业务模块调用

商店与签到模板
`/shop list` 或 `/商店 列表` 显示商品分类。`/shop 立绘|skin|皮肤|角色立绘` 展示立绘商品，`/shop 签到|签到模板|sign` 展示签到模板（竖线表示任选一个别名）。
`/shop buy skin01` 购买立绘，`/shop buy sign02` 或 `/shop buy sign03` 以 500 积分购买 P3 水色模板或尼尔档案模板。购买只接受带分类前缀的商品编号，不支持纯数字编号。
默认模板 `sign01` 免费发放至库存：新用户注册时领取，已注册用户在启动时补发。`/查询 签到模板` 查看持有情况，`/设置 签到模板 sign01`、`sign02` 或 `sign03` 切换签到及资料卡片模板。
正式模板为 `daily_sign_01.html`、`daily_sign_02.html`、`daily_sign_03.html`，商店展示图存放于 `assets/image/sign/`；增加模板时在商店目录中登记固定商品编号、名称及价格。

积分查询
使用 `/积分 查询`、`/查询 积分` 或 `/point query` 以文字查看自己的积分数量与全体用户排名，两处入口共用同一个处理方法，未注册时提示先注册。排名按积分降序、同分按用户编号排序，不受前20名限制。签到卡片、个人排名、群榜和总榜均排除超级用户，超级用户查询时显示积分与“未参与排名”。

积分转账
使用全局命令起始符，例如 `/积分 转账 @用户 100`、`/积分 转账 1683550817 100`，
也可使用 `/point transfer 1683550817 100`。双方须已注册，转账数量为正整数，不能向自己转账。

积分排名
使用 `/积分 排名`、`/point List`（也支持 `list`）发送三条节点的合并消息：查询提示、本群积分排名、全部用户积分排名。
两份榜单各展示前 20 名，按积分降序排列，格式为 `昵称（16**17）  100 积分`，QQ 号只保留前后各两位，中间固定两个星号。

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

### YouTube 下载环境

YouTube 信息获取和视频下载统一启用 Deno / Node 运行时，并允许从官方 GitHub 下载 EJS 求解脚本作为备用。
依赖使用 `yt-dlp[default]` 安装匹配的 EJS，避免首次下载依赖 GitHub；现有环境更新依赖后重启机器人。
非 Docker 部署需将 Node 22 及以上（推荐 Node 24），或 Deno 2.3 及以上加入机器人进程的 `PATH`。
Docker 镜像已包含 Node 24，更新后需重新构建镜像。

登录凭据优先读取当前环境配置中的字符串：

```dotenv
YTB_CK="name=value; name2=value2"
```

`YTB_CK` 为空时，依次读取工作目录的 `ytb_cookies.txt`、`assets/ytb_cookies.txt`，文件须为 Mozilla/Netscape 格式。
Cookie 文件仅在内存中使用，不回写原文件；Docker 可通过现有 `./assets:/app/assets` 挂载提供。
登录凭据不可提交到 Git，字符串配置与 Cookie 文件均需定期更新；能否访问年龄限制内容仍取决于有效会话和账号权限。

Quan666/ELF_RSS

RSS/RSSHub动态订阅、更新推送、图片处理、去重及可选aria2种子下载上传
此插件针对MadokaBot进行特殊适配
