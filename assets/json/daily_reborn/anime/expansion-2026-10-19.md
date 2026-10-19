# 二次元番剧扩充记录

资料版本 `2026.10.19.6`，核对日期 2026-10-19。本次新增 20 部：日常／音乐 10 部、异世界 10 部，总计 41 部。只增补现有结构的数据、来源与标题图，不改动投胎算法、命令、持久化键或已有作品设置。

## 玩法口径

- 全部新增作品权重为 1，与原有作品相同；当前日常 17/41、异世界 14/41、战斗 10/41。分类是题材预设，不是原作官方分类或风险统计。
- 匿名居民沿用本模式的人类寿命与人生算法，不默认继承主角身份、特殊体质、无限寿命或复活能力；不会保证加入某个乐队。
- 日常作品不配置致命剧情事件。成员矛盾、解散、比赛失利、舞台紧张均不作为致命事件。《向山进发》按户外日常设为和平，保留通用意外的低风险。
- 《Re：从零开始的异世界生活》的魔女教袭击与白鲸讨伐、《无职转生》的转移事件、《盾之勇者成名录》的波，依据官方剧情资料收录；匿名人物被波及、遇难概率、年龄和事件权重均为游戏设置，不代表原作人物结局或实际时间线。
- 新增多人婚育开关仅为玩法选择：《暗杀贵族》《无职转生》《异世界悠闲农家》开启，其他新增作品关闭。原有设置不变。
- 《Angel Beats!》继续暂缓，不进入抽取名单。MyGO按其动画篇章收录一项，不按每个乐队或后续篇章重复增加同一背景的权重。

## 官方资料与标题图

各作品对应独立 JSON；资料来源在 `sources.json`，本表单独记录标题图来源。图片随仓库放置于 `assets/image/reborn/`，投胎渲染无需请求官网。标题图可能带有已播放季度或周年标识，不表示把不同季度拆成不同世界；盾勇标题图直接提取自第三季官网的内嵌 SVG，其余为官网原始图片。

| 作品 | 本地标题图 | 资料 | 图源 |
| --- | --- | --- | --- |
| 孤独摇滚！ | `bocchi_the_rock.svg` | [官方资料](https://bocchi.rocks/tv/) | [标题图](https://bocchi.rocks/tv/assets/img/common/footer/ttl_logo.svg) |
| 轻音少女 | `k_on.jpg` | [官方资料](https://www.tbs.co.jp/anime/k-on/) | [标题图](https://www.tbs.co.jp/anime/k-on/images/logo.jpg) |
| Girls Band Cry | `girls_band_cry.png` | [官方资料](https://girls-band-cry.com/story/) | [标题图](https://girls-band-cry.com/wp-content/themes/gbc_v1-1/assets/images/common/logo.png) |
| BanG Dream! It's MyGO!!!!! | `bang_dream_mygo.svg` | [官方资料](https://anime.bang-dream.com/mygo/story/) | [标题图](https://anime.bang-dream.com/mygo/wordpress/wp-content/themes/mygo_v1/assets/images/common/logo.svg) |
| 夜晚的水母不会游泳 | `jellyfish.png` | [官方资料](https://yorukura-anime.com/) | [标题图](https://yorukura-anime.com/assets/images/common/logo.png) |
| 吹响！上低音号 | `euphonium.webp` | [官方资料](https://tv3rd.anime-eupho.com/) | [标题图](https://tv3rd.anime-eupho.com/img/common/eupho3-logo.webp) |
| 悠哉日常大王 | `non_non_biyori.svg` | [官方资料](https://nonnontv.com/tvanime/) | [标题图](https://nonnontv.com/tvanime/wp-content/themes/nonnon_tvanime/assets/img/common/gnav/logo.svg) |
| 请问您今天要来点兔子吗？ | `gochiusa.svg` | [官方资料](https://gochiusa.com/bloom/) | [标题图](https://gochiusa.com/bloom/core_sys/images/main/common/logo_yoko.svg) |
| 摇曳百合 | `yuru_yuri.png` | [官方资料](https://yuruyuri.com/3hai/) | [标题图](https://yuruyuri.com/3hai/img/head/logo.png) |
| 向山进发 | `yama_no_susume.png` | [官方资料](https://yamanosusume-ns.com/) | [标题图](https://yamanosusume-ns.com/core_sys/images/main/common/logo.png) |
| 世界顶尖的暗杀者，转生为异世界贵族 | `assassin_aristocrat.png` | [官方资料](https://ansatsu-kizoku.jp/) | [标题图](https://ansatsu-kizoku.jp/wp-content/themes/ansatsu-kizoku/assets/images/common/header/logo.png) |
| 为美好的世界献上祝福！ | `konosuba.png` | [官方资料](https://konosuba.com/3rd/introduction/) | [标题图](https://konosuba.com/3rd/assets/img/common/logo.png) |
| Re：从零开始的异世界生活 | `re_zero.webp` | [官方资料](https://re-zero-anime.jp/tv/story/tv2.html) | [标题图](https://re-zero-anime.jp/tv/images/common/logo.webp) |
| 无职转生～到了异世界就拿出真本事～ | `mushoku_tensei.png` | [官方资料](https://mushokutensei.jp/) | [标题图](https://mushokutensei.jp/wp-content/themes/mushoku_re/img/common/img_logo03.png) |
| 关于我转生变成史莱姆这档事 | `tensura.png` | [官方资料](https://www.ten-sura.com/anime/tensura) | [标题图](https://www.ten-sura.com/4GfGdAp7/wp-content/themes/tensura_portal/assets/images/logo.png) |
| 盾之勇者成名录 | `shield_hero.svg` | [官方资料](https://shieldhero-anime.jp/3rd/) | [标题图](https://shieldhero-anime.jp/3rd/) |
| 想要成为影之实力者！ | `eminence_in_shadow.svg` | [官方资料](https://shadow-garden.jp/2nd/) | [标题图](https://shadow-garden.jp/2nd/assets/img/common/logo.svg) |
| 转生成为了只有乙女游戏破灭Flag的邪恶大小姐 | `hamefura.png` | [官方资料](https://hamehura-anime.com/) | [标题图](https://hamehura-anime.com/2nd/wp-content/themes/hamehura-2nd/_assets/images/_common/logo/logo_yoko_color@2x.png) |
| 小书痴的下克上 | `bookworm.png` | [官方资料](https://booklove-anime.jp/story/) | [标题图](https://booklove-anime.jp/images/common/logo_booklove.png) |
| 异世界悠闲农家 | `isekai_farming.png` | [官方资料](https://nonbiri-nouka.com/) | [标题图](https://nonbiri-nouka.com/images/top/main_img_logo_pc.png) |

## 静态检查

核对 JSON 语法、作品清单、唯一标识、正权重、分类与危险度、来源引用、事件配置，以及所有标题图的存在性与文件格式。不启动机器人，不运行随机模拟或额外测试。
