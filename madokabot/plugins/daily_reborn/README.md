# 每日投胎 · Daily Reborn

命令：`reborn`，别名 `每日投胎`、`投胎`、`daily_reborn`，均遵循全局 `COMMAND_START`。
例如起始符为 `/` 时，使用 `/每日投胎`。

每位用户按上海时间每天抽取一次，跨群、私聊共用结果，无需注册。
重复使用命令返回当天结果，数据库联合主键保证并发请求及重启后不会重新抽取。
记录表为 `madoka_daily_reborn_record`，随项目现有数据库初始化流程建表。
生成结果成功保存后才返回；图片失败时发送文字结果，之后仍可重新渲染同一结果。

## 人口数据

- 来源：[联合国 World Population Prospects 2024](https://population.un.org/wpp/)，当前快照来自 2025 年更新的官方 `GEN/01/REV1` 工作簿。
- 原始文件：[Demographic Indicators Compact](https://population.un.org/wpp/assets/Excel%20Files/1_Indicator%20(Standard)/EXCEL_FILES/1_General/WPP2024_GEN_F01_DEMOGRAPHIC_INDICATORS_COMPACT.xlsx)。
- 当前使用 2026 年 Medium variant（中方案）预测，共 237 个国家/地区。这是统一口径预测，不是各国当年的已公布实测值。
- 出生地抽样概率 = 当地年度出生人数 / 全球各地区年度出生人数之和。直接使用原表出生人数，单位从千人转换为人；不会将粗出生率直接作为权重。
- 性别抽样使用原表出生性别比：男婴概率 = 性别比 /（性别比 + 100）。
- 中国内地、台湾、香港、澳门保留原始统计分区，以免重复统计，名称统一使用中国内地、中国台湾、中国香港、中国澳门。
- 使用许可：[CC BY 3.0 IGO](https://creativecommons.org/licenses/by/3.0/igo/)。

人口快照不在运行时自动联网更新。年度切换或联合国数据更新后，在项目根目录手动运行：

```powershell
.venv/Scripts/python.exe madokabot/plugins/daily_reborn/update_data.py --year 2027
```

也可用 `--workbook <已下载的xlsx路径>` 和 `--map <已下载的GeoJSON路径>` 复用原始文件。
更新脚本校验完整性后写入 `data/population.json`、`data/world_map.json`；更新完成需重启机器人以刷新内存缓存。
快照与文字结果保留实际使用的数据年份，快照不会随系统年份静默冒充最新数据。

## 地图与评分

地图来自 [Natural Earth 地理单元数据](https://github.com/nvkelso/natural-earth-vector/blob/master/geojson/ne_10m_admin_0_map_units.geojson)，
按经纬度等距投影生成本地 SVG 路径，简化用于娱乐示意，定位点代表地区而非具体出生城市。
台湾、香港、澳门与中国共用高亮编号 `CHN`；抽中中国任一统计分区时都会高亮包含台湾的中国范围。
地图数据为 [Public domain](https://www.naturalearthdata.com/about/terms-of-use/)。

家境、健康、智力、魅力、运气五项属性各随机取 1～100，彼此独立，且不按出生地或性别加减分。
综合评分为五项平均值四舍五入；85 分及以上 SSR、70 分及以上 SR、50 分及以上 R，其余 N。
属性、评级和寄语均为游戏设定。
