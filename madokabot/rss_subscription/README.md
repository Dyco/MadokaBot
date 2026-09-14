# RSS 订阅

基于 [Quan666/ELF_RSS]适配到 MadokaBot 的 RSS 订阅插件。

## 命令

群聊按 MadokaBot 的 `COMMAND_START`、昵称或 @ 规则使用；私聊仅允许超级用户使用。`加入`、`上传文件`、`选择文件` 和 `重试` 依赖当前群，仍只能在群聊中执行。
```text
RSS 添加 <名称> <RSS 地址>             添加订阅（也可使用：订阅 添加）
RSS 加入 <订阅名>                     让当前群加入已有订阅
RSS rsshub_add <路由名>               交互式添加 RSSHub 路由
RSS 删除 <名称 ...>                   取消当前群订阅/删除订阅
RSS 查看 [名称]                       查看订阅详情
RSS 查看全部 [关键词]                 查看订阅列表，关键词支持正则
RSS 修改 <名称 ...> 属性=值            修改订阅设置
RSS cookies <名称> <cookies>           设置订阅 cookies
RSS 上传文件 <磁力或 torrent 地址>     手动下载并上传群文件
RSS 选择文件 <GID> <编号>              选择多文件任务，如 1,3-5
RSS 重试 <GID>                        重试上传下载完成但上传失败的文件
RSS 删除文件 <GID>                    删除下载文件及对应任务记录
RSS 文件记录                          查看当前群保留的下载文件记录
RSS 终止 <GID>                        终止下载任务（也可使用 close）
```

`RSS` 和 `订阅` 是同一个命令的两个入口；子命令也支持对应的英文名称和历史别名。

添加订阅时会检查规范化后的实际地址；如果地址已经存在，会返回现有订阅名，并提示当前群使用 `RSS 加入 <订阅名>` 共用该订阅。多群共享订阅只执行一份抓取任务并共用更新缓存，第一个加入的群负责修改订阅设置，后加入的群可以接收推送或使用 `RSS 删除 <订阅名>` 退出。

手动使用 `RSS 上传文件` 时，单文件种子会直接开始下载；多文件种子会先暂停，并以 `编号.文件名[大小]` 的格式列出文件。上传发起者在 60 秒内引用选择提示、回复 `1,2,3` 或 `1,3-5` 即可开始下载，也可以使用 `RSS 选择文件 <GID> <编号>`。磁力链接需要先获取种子元数据，因此文件列表和用于选择的实际 GID 会稍后发送。RSS 订阅自动触发的下载仍会下载全部文件，下载完成后只上传 aria2 标记为已选择的文件。

`change` 支持 RSS 的 `qq`、`qun`、`time`、`proxy`、`ot`、`op`、`ohp`、`downpic`、`downopen`、`wkey`、`bkey`、`upgroup`、`mode`、`img_num`、`stop`、`forward` 和 `rm_list` 等属性。

去重模式为 `link`、`title`、`image`，可加 `or` 使用任一条件匹配；设置为 `-1` 可关闭。`time` 可以是分钟数，也可以是五段 cron 字段（用 `_` 分隔）。

## 代码结构

- `command/`：Alconna 命令注册与交互处理。
- `subscription.py`：订阅模型、持久化和去重模式定义。
- `feed.py`、`scheduler.py`：订阅抓取与定时调度。
- `parser.py`、`handlers.py`：通用处理管线及默认处理器。
- `routes/`：Pixiv、微博、Bilibili 等站点的特化处理器。
- `cache.py`：更新判断、JSON 缓存和去重数据库。
- `content.py`、`images.py`：正文与媒体内容处理。
- `download.py`、`delivery.py`：下载后端及消息投递。
- `utils.py`：代理、Bot 查询、目标校验等通用辅助函数。

## MadokaBot 配置适配

- 网络请求统一优先使用 MadokaBot 的 `PROXY`；订阅的 `proxy=1` 表示该订阅启用此代理。
- 订阅、订阅缓存和去重数据库统一存放在 LocalStore 的 `madokabot_rss_subscription` 数据目录中。当前 `.env.prod` 的 `LOCALSTORE_DATA_DIR` 为 `./assets/data`，因此默认目录是 `assets/data/madokabot_rss_subscription/`。
- `SUPERUSERS`、`NICKNAME` 直接使用 NoneBot/MadokaBot 的通用配置。
- 原 ELF_RSS 的 `RSS_PROXY` 仍可作为没有 `PROXY` 时的兼容回退，但新部署应只配置 `PROXY`。
- `FIRST_BOOT_MESSAGE` 和 `BOOT_SUCCESS_MESSAGE` 可分别修改首次启动、启动成功时发送的提示文本。

图片下载/压缩、Pixiv/微博/Bilibili/Twitter/Danbooru/Yande.re/YouTube 特殊解析、aria2 种子下载上传、消息转发和多目标订阅均保留原功能；RSS 内容直接按原文展示，不再调用翻译服务。aria2 由 MadokaBot 通过 JSON-RPC 控制，Python 依赖已经包含在项目环境中，但 `aria2c` 程序需要在服务器上单独安装并运行。

## Danbooru 配置

Danbooru 订阅会把 `/posts.atom` 和 `/posts.json` 地址统一转换为官方 `/posts.json` API 请求，并保留原地址中的 `limit`、`tags` 等查询参数。程序直接使用 API 返回的作品页、发布时间、评分、标签以及预览/大图地址，不再抓取作品 HTML 页面。

公开作品无需登录即可读取。按照 Danbooru API 的客户端标识建议，可以配置自己的 Danbooru 用户 ID；需要访问账户可见内容时，再同时配置用户名和 API Key：

```ini
DANBOORU_USER_ID=123456
DANBOORU_LOGIN="your_name"
DANBOORU_API_KEY="your_api_key"
```

用户名和 API Key 必须同时配置，API Key 应当只保存在环境配置中。已有的 Danbooru Atom 订阅不需要删除重建；部署新代码并重新启用订阅后会自动改走 JSON API。

## aria2 配置（Linux）

Debian/Ubuntu 可以安装 aria2：

```bash
sudo apt update
sudo apt install aria2
```

启动 aria2 RPC 示例（仓库中也提供了 `aria2.conf.example`）：

```bash
aria2c \\
  --enable-rpc=true \\
  --rpc-listen-all=false \\
  --rpc-listen-port=6800 \\
  --rpc-secret=change-this-secret \\
  --dir=/srv/madoka/downloads \\
  --continue=true
```

建议使用 systemd 或 Docker 保持 aria2c 常驻运行。`aria2c` 的下载目录必须与 `ARIA2_DOWNLOAD_PATH` 相同，并且运行 MadokaBot 的用户需要有读取权限，aria2 运行用户需要有写入权限。

对应 `.env.prod` 配置：

```ini
ARIA2_RPC_URL="http://127.0.0.1:6800/jsonrpc"
ARIA2_RPC_SECRET="change-this-secret"
ARIA2_DOWNLOAD_PATH="/srv/madoka/downloads"
ARIA2_ACQUIRE_TIMEOUT=60
ARIA2_FILE_CLEANUP_DELAY=3600
ARIA2_MAX_FILE_SIZE_MB=512
ARIA2_MAX_TOTAL_SIZE_MB=1024
RSS_AUTO_FORWARD=true
# MadokaBot 通用媒体配置，由 madoka_bundle 统一读取，RSS 与 Resolver 共用
VIDEO_MESSAGE_MAX_MB=95
VIDEO_COMPRESS_MAX_MB=300
VIDEO_COMPRESS_TARGET_MB=90
FFMPEG_PATH=ffmpeg
FFPROBE_PATH=ffprobe
FFMPEG_TIMEOUT=1800
GROUP_FILE_MAX_MB=2048
GROUP_FILE_UPLOAD_TIMEOUT=3600
RSS_UPLOAD_VERIFY_DELAY=3600
RSS_UPLOAD_MAX_RETRIES=1
RSS_UPLOAD_CONCURRENCY=1
DOWN_STATUS_MSG_GROUP="[]"
DOWN_STATUS_MSG_DATE=90
DOWN_STATUS_MSG_RECALL_DELAY=60
```

`FFMPEG_TIMEOUT` 控制单次 FFmpeg/FFprobe 处理时限，默认 `1800` 秒；超时后会终止子进程并释放上传队列。群文件核验接口连续异常时同样受 `RSS_UPLOAD_MAX_RETRIES` 限制，不会无限期循环核验。

订阅开启 `downopen=1` 后，RSS 中的磁力链接或 `.torrent` 链接会提交给 aria2。机器人提交的任务会设置 `seed-time=0`，下载完成后不继续做种。`ARIA2_ACQUIRE_TIMEOUT` 控制 torrent 链接、aria2 RPC 初始信息及磁力元数据的获取时限，单位为秒，默认是 `60`；获取失败或超时后会放弃任务，进入正式文件下载后不再受该时限影响。`ARIA2_FILE_CLEANUP_DELAY` 控制上传处理结束后的文件保留时间，单位为秒，默认是 `3600`；设为 `0` 可以关闭自动清理。`ARIA2_MAX_FILE_SIZE_MB` 限制单个普通文件大小，默认是 `512` MiB；`ARIA2_MAX_TOTAL_SIZE_MB` 限制单个种子任务的总大小，默认是 `1024` MiB。视频另受 `VIDEO_COMPRESS_MAX_MB` 限制，超过默认 `300` MiB 时不会开始内容下载。触发任一大小限制时只会停止内容文件，已经取得的 `.torrent` 仍会加入上传队列。`DOWN_STATUS_MSG_DATE` 控制下载进度检查及提示间隔，单位为秒，默认是 `300`；`DOWN_STATUS_MSG_RECALL_DELAY` 控制每条进度消息独立撤回的延迟，默认是 `110` 秒，设为 `0` 时不自动撤回。

下载完成后，原始 `.torrent` 文件和下载内容会一起写入持久化记录，再进入默认单并发的上传队列。视频大小不超过 `VIDEO_MESSAGE_MAX_MB`（默认 `95` MiB）时直接发送；超过 `95` 且不超过 `VIDEO_COMPRESS_MAX_MB`（默认 `300` MiB）的视频通过 FFmpeg 双遍压缩到约 `VIDEO_COMPRESS_TARGET_MB`（默认 `90` MiB）后发送；超过 `300` MiB 的视频拒绝发送，其他文件上传为群文件。请确保 `FFMPEG_PATH` 和 `FFPROBE_PATH` 指向可执行程序。上传前会检查 Bot 群关系、本地文件完整性、群文件状态和同名同大小文件；重复群文件会直接跳过。`GROUP_FILE_UPLOAD_TIMEOUT` 控制通用群文件上传 API 等待时间，默认 `3600` 秒。上传 API 返回后不会立即反查，而是在 `RSS_UPLOAD_VERIFY_DELAY`（默认 `3600` 秒）后读取群文件列表确认结果；未找到时最多自动重传 `RSS_UPLOAD_MAX_RETRIES` 次，默认 `1` 次。`RSS_UPLOAD_CONCURRENCY` 默认是 `1`。GID、任务名、文件路径、大小、目标群、尝试时间、尝试次数、重传次数、核验时间、成功状态和最近错误都会保存在 LocalStore 数据目录的 `download_records.json`，应用重启后会自动恢复未完成的队列和核验任务，也可以使用 `RSS 文件记录` 查看。全部发送成功后才会重新开始文件清理倒计时；不再需要保留文件时，可以使用 `RSS 删除文件 <GID>`。若 aria2 和 MadokaBot 使用 Docker，两个容器必须挂载同一个下载目录，并使用相同的容器内路径；此时 `ARIA2_RPC_URL` 应填写 aria2 服务名（例如 `http://aria2:6800/jsonrpc`），不能填写指向 MadokaBot 容器自身的 `127.0.0.1`。

RSS 自动更新默认通过合并消息发送；`RSS_AUTO_FORWARD=false` 可以恢复为逐条消息，此时仍可用订阅的 `forward` 设置单独开启合并消息。合并消息会按“订阅更新、链接地址、详情信息”拆分节点。

使用 `RSS 终止 <GID>` 或 `RSS close <GID>` 可以停止尚未完成的 aria2 任务，同时停止机器人对该任务的进度检查。该命令不会删除已经下载到磁盘的完整或部分文件。
