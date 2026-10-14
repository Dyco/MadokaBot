# RhythmGame_OCM

支持 [舞萌 DX](https://maimai.lxns.net/docs/api/maimai) 与 [中二节奏](https://maimai.lxns.net/docs/api/chunithm)，通过 LXNS 开发者 API 查询资料、单谱成绩和 B50。
插件由项目统一加载器自动加载，无需手动添加注册项；群聊和私聊均可使用。
B50 查询使用项目共用的表情回应，渲染完成后引用指令消息仅回复图片，不发送额外进度文字。
舞萌与中二图片水印统一为 `MADOKABOT VER <版本号>`，版本号通过公共 `get_bot_version()` 获取。

## 配置

在机器人使用的环境配置文件中填写后重启：

```dotenv
# 必须使用开发者 Token，个人 API Token 不适用于本插件。
RHYTHMGAME_LXNS_TOKEN="填写你的开发者Token"
# 请求超时，单位秒。
RHYTHMGAME_REQUEST_TIMEOUT=20
# 缺失素材下载间隔，单位秒，最小 0.5。
RHYTHMGAME_ASSET_INTERVAL=1
# 舞萌 B50 底图主题，对应 image/maimai/pic 下的文件夹。
RHYTHMGAME_MAIMAI_THEME="prism_plus"
```

未配置 Token 时插件仍可加载，查分时会给出配置提示；公共曲目和曲绘更新不需要 Token。
舞萌主题目前可选 `prism_plus`、`circle`，默认 `prism_plus`。
底图和版本 Logo 分别读取该目录的 `b50.png`、`logo.png`，评级图标也随主题切换。
单谱卡片按难度使用 `pic/b50_score_basic.png` 至 `pic/b50_score_remaster.png` 的完整底板，
圆形 FC／AP 与 FS 图标读取公共 `pic/UI_CHR_PlayBonus_*.png`，没有对应状态时保留灰色空位。
顶部玩家信息按名牌底图叠加头像、DX Rating、姓名、段位、阶级与称号。
DX Rating 数字使用 `pic/UI_NUM_Drating_*.png`，底板在当前主题目录内按分段选择：
`01`～`05` 分别从 0、2000、4000、6000、8000 起，`06` 从 10000 起，之后每 1000 升一级，`11` 对应 15000。
主题缺少目标编号（例如 16000 对应的 `12`）时向下查找最高可用底板；顶部显示玩家资料 Rating。
不要在聊天中发送 Token。玩家需要先在 LXNS 同步成绩，并开放第三方获取玩家资料与成绩权限。

## 命令

### 舞萌 DX

下列 `/` 仅为示例，所有指令遵循全局 `COMMAND_START`。`mai` 别名为 `maimai`、`舞萌`。

| 命令 | 功能 |
| --- | --- |
| `/b50 [目标]` 或 `/mai b50 [目标]` | 生成 B50 图片 |
| `/mai info [目标]` | 查询资料、Rating、称号和同步时间 |
| `/mai score <曲目ID> <难度> <SD或DX> [目标]` | 查询指定谱面的最佳成绩 |
| `/mai bind <15位好友码>` | 验证玩家存在后保存当前 QQ 的绑定 |
| `/mai unbind` | 删除机器人内的绑定 |
| `/mai update` | 超级用户刷新曲目、定数并增量补齐普通曲绘 |
| `/mai help` | 查看完整用法 |

目标可填写 15 位好友码、QQ 号或 @用户。省略时先查自己的机器人绑定，再使用自己的 QQ 查询 LXNS。
QQ／@目标同样优先使用机器人绑定。绑定仅是查分目标设置，不修改 LXNS 账号，也不验证账号所有权。
解绑后仍可通过 LXNS 自己的 QQ 绑定查询；查询其他人的好友码不会改变自己的绑定。
绑定保存到数据库 `madoka_rhythmgame_maimai_binding`，不要求注册机器人积分账号。

难度支持绿、黄、红、紫、白，或 `0`～`4`、`BASIC`～`Re:MASTER`。
例如 `/mai score 834 白 SD`。普通曲目 ID 大于 10000 时按 LXNS 规则取余，SD／DX 由类型参数决定。
本阶段暂不支持宴会场成绩查询。

B50 分组直接使用 LXNS 的旧版本 B35 与现版本 B15，**不按 SD／DX 类型分组**。
图片展示达成率、向下取整后的单谱 Rating、定数、DX 分数与星级、FC／FS 标记。
不足 50 条时保留空位；分组标题仅显示“旧曲 B35”和“新曲 B15”，不渲染分组总分或汇总卡片。
这是 LXNS 已同步的缓存成绩，查分命令不会主动从游戏 NET 同步。

### 中二节奏

`chu` 别名为 `chuni`、`chunithm`、`中二`、`中二节奏`，同样遵循全局命令起始符。

| 命令 | 功能 |
| --- | --- |
| `/cb50 [目标]` 或 `/chu b50 [目标]` | 生成中二 B50 图片，并单独展示 Selection 10 |
| `/chu info [目标]` | 查询 Rating、等级、转生、称号、OVER POWER 与同步时间 |
| `/chu score <曲目ID> <难度> [目标]` | 查询指定谱面的最佳成绩，无需 SD／DX 参数 |
| `/chu bind <15位好友码>` | 保存当前 QQ 的中二绑定 |
| `/chu unbind` | 仅删除机器人内的中二绑定 |
| `/chu update` | 超级用户更新中二曲目定数并增量补齐曲绘 |
| `/chu help` | 查看中二用法 |

目标规则与舞萌一致，但读取独立的中二绑定表 `madoka_rhythmgame_chunithm_binding`。
两种游戏共用 `RHYTHMGAME_LXNS_TOKEN`；绑定、解绑或查询中二均不会改动舞萌账号。

难度支持绿、黄、红、紫、黑、WE，或 `0`～`5`、`BASIC`、`ADVANCED`、`EXPERT`、`MASTER`、`ULTIMA`、`WORLD'S END`（包含空格时加引号）。
例如 `/chu score 3 黑` 查询 ULTIMA，`/chu score 8000 WE` 查询 WORLD'S END。
中二曲目 ID 原样发送，不采用舞萌的取余规则。

当前中二 Rating 构成按 LXNS 的旧曲 `bests`（B30）与新曲 `new_bests`（B20）分组。
`selections`（S10）单独展示，不计入 B50 平均 Rating；不使用旧版本 Recent 10 代替新曲 B20。
分组内按 Rating、分数排序，不足数量时保留空位，平均 Rating 按固定席位数计算，缺位计零。
图片同时显示 B50 平均 Rating 与玩家资料 Rating，两者来自不同缓存时可能有差异。
四位小数的 B50 平均值使用十进制计算并截断，单谱 Rating 直接来自 LXNS。

中二图片展示曲绘、分数、定数、评级、通关状态、FC／AJ／AJC，以及金链／铂链。
玩家角色、地图头像、名牌版和图片称号按需下载，称号为普通文字时直接显示名称。

## 资源更新

沿用公共 `ASSETS_PATH` 配置，下列路径均相对于该目录：

| 路径 | 内容 |
| --- | --- |
| `image/maimai/cover/<ID>.png` | 普通曲绘，复用已有资源包 |
| `image/maimai/pic/` | 本地 B50 背景、成绩素材、段位与状态图标 |
| `image/maimai/icon/`、`image/maimai/plate/` | 查询时按需缓存的头像和姓名框 |
| `font/maimai/font/ResourceHanRoundedCN-Bold.ttf` | 已准备的中文字体 |
| `json/maimai/catalog.json` | LXNS 曲目、版本、定数及物量快照 |
| `image/chunithm/cover/<ID>.png` | 中二曲绘，WORLD'S END 复用 `origin_id` 原曲曲绘 |
| `image/chunithm/pic/` | 本地黑金背景与占位曲绘 SVG |
| `image/chunithm/character/`、`icon/`、`plate/`、`trophy/` | 玩家角色、地图头像、名牌版与图片称号 |
| `font/chunithm/font.ttf`、`numbers.otf` | 独立保存的中文字体和数字字体 |
| `json/chunithm/catalog.json` | 中二曲目、定数、版本及物量快照 |

查分时曲目快照超过 24 小时会自动刷新；网络异常时使用已有快照。
曲绘、头像和姓名框优先使用本地缓存，仅下载缺失文件；与 `cover/0.png` 相同的占位曲绘也会尝试补齐。
远端未收录曲绘时使用本地占位图。下载使用 LXNS 官方资源地址，按配置限速，不向资源服务器发送 Token。
普通曲绘保留已有文件，界面背景和字体继续使用你准备的资源包。宴会场不请求独立曲绘。
完整增量更新期间查分使用已有资源；更新失败保留已下载文件，再次执行可继续补齐。
中二曲绘从 LXNS 官方中二资源目录获取，缺失时使用本地 SVG 占位图。
完整更新最多保留三个下载请求，共用请求间隔；并发不会取消限速。

也可以在项目根目录直接运行更新工具，无需启动机器人：

```powershell
.venv/Scripts/python.exe madokabot/plugins/RhythmGame_OCM/update_resources.py
# 中二节奏，使用独立资源目录；省略 --game 时仍更新舞萌。
.venv/Scripts/python.exe madokabot/plugins/RhythmGame_OCM/update_resources.py --game chunithm
```

使用自定义资源根目录时显式传入，独立脚本不会读取机器人的环境配置：

```powershell
.venv/Scripts/python.exe madokabot/plugins/RhythmGame_OCM/update_resources.py --assets-dir D:/BotAssets --interval 1
```

B50 使用项目已有 `nonebot_plugin_htmlrender` 浏览器实例，部署环境需要安装其 Chromium。
所有文本读写均显式使用 UTF-8。
