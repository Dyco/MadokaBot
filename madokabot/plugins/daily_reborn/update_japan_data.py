"""手动将厚生劳动省人口表和 N03 GeoJSON 转为日本投胎快照，地图处理需安装项目的 data 可选依赖。"""

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from shapely.geometry import shape
from shapely.ops import unary_union

DATA_DIR = Path(__file__).parent / "data"
POPULATION_URL = "https://www.mhlw.go.jp/toukei/saikin/hw/jinkou/kakutei25/xls/06_hyoR07.xlsx"
MAP_URL = "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N03-2026.html"
XML = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
# 名称按官方表内的都道府县代码顺序排列，展示时使用简体中文。
PREFECTURE_NAMES = (
    "北海道", "青森县", "岩手县", "宫城县", "秋田县", "山形县", "福岛县",
    "茨城县", "栃木县", "群马县", "埼玉县", "千叶县", "东京都", "神奈川县",
    "新潟县", "富山县", "石川县", "福井县", "山梨县", "长野县", "岐阜县",
    "静冈县", "爱知县", "三重县", "滋贺县", "京都府", "大阪府", "兵库县",
    "奈良县", "和歌山县", "鸟取县", "岛根县", "冈山县", "广岛县", "山口县",
    "德岛县", "香川县", "爱媛县", "高知县", "福冈县", "佐贺县", "长崎县",
    "熊本县", "大分县", "宫崎县", "鹿儿岛县", "冲绳县",
)


def read_population(workbook: Path) -> dict:
    """读取 2025 年第四表中的 47 个地区及男女出生人数，不混入全国或指定城市再揭数据。"""
    with ZipFile(workbook) as archive:
        book = ET.fromstring(archive.read("xl/workbook.xml"))
        entry = next(sheet for sheet in book.find("m:sheets", XML) if sheet.get("name") == "第４表")
        relation_id = entry.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        relations = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        target = next(relation.get("Target") for relation in relations if relation.get("Id") == relation_id)
        target = target.lstrip("/") if target.startswith("/") else "xl/" + target
        sheet = ET.fromstring(archive.read(target))
        rows = {int(row.get("r")): row for row in sheet.findall("m:sheetData/m:row", XML)}
        countries = []
        for code, name in enumerate(PREFECTURE_NAMES, start=1):
            cells = {
                "".join(char for char in cell.get("r") if char.isalpha()): cell.findtext("m:v", namespaces=XML)
                for cell in rows[code + 7]
            }
            births, male, female = (int(cells[column]) for column in ("C", "D", "E"))
            if births != male + female or min(male, female) <= 0:
                raise ValueError(f"日本出生人口数据无效：{name}")
            countries.append({
                "code": f"JP-{code:02d}", "name": name, "births": births,
                "male_births": male, "female_births": female, "sex_ratio": male / female * 100,
            })
    return {
        "source": "日本厚生劳动省 2025 年人口动态统计（确定数）", "source_url": POPULATION_URL,
        "year": 2025, "births_note": "日本人出生统计，按孩子住所归属都道府县；地图点位为游戏示意",
        "countries": countries,
    }


def prepare_map(source_path: Path, population: dict) -> dict:
    """按行政代码合并 N03 边界并简化细小海岸线，生成与现有卡片共用的离线路径。"""
    groups = {row["code"]: [] for row in population["countries"]}
    source = json.loads(source_path.read_text(encoding="utf-8"))
    for feature in source["features"]:
        code = "JP-" + feature["properties"]["N03_007"][:2]
        geometry = shape(feature["geometry"])
        polygons = [geometry] if geometry.geom_type == "Polygon" else geometry.geoms
        groups[code].extend(polygon.simplify(.003) for polygon in polygons if polygon.area >= .000002)
    del source
    geometries = {code: unary_union(polygons) for code, polygons in groups.items()}
    if any(geometry.is_empty for geometry in geometries.values()):
        raise ValueError("日本地图必须覆盖全部 47 个都道府县")
    cosine = math.cos(math.radians(35))
    left = min(geometry.bounds[0] for geometry in geometries.values()) * cosine
    right = max(geometry.bounds[2] for geometry in geometries.values()) * cosine
    top = -max(geometry.bounds[3] for geometry in geometries.values())
    bottom = -min(geometry.bounds[1] for geometry in geometries.values())
    scale = min(952 / (right - left), 660 / (bottom - top))
    offset_x = 24 + (952 - (right - left) * scale) / 2
    offset_y = 20 + (660 - (bottom - top) * scale) / 2

    def project(longitude: float, latitude: float) -> tuple[float, float]:
        """以北纬 35 度作等距圆柱投影，边界、网格与定位使用相同坐标。"""
        return round(offset_x + (longitude * cosine - left) * scale, 3), round(offset_y + (-latitude - top) * scale, 3)

    regions = []
    for row in population["countries"]:
        geometry = geometries[row["code"]]
        polygons = [geometry] if geometry.geom_type == "Polygon" else list(geometry.geoms)
        paths = []
        for polygon in polygons:
            for ring in (polygon.exterior, *polygon.interiors):
                points = [project(*point) for point in ring.coords]
                paths.append("M" + "L".join(f"{x},{y}" for x, y in points) + "Z")
        anchor = max(polygons, key=lambda polygon: polygon.area).representative_point()
        marker_x, marker_y = project(anchor.x, anchor.y)
        regions.append({
            "code": row["code"], "name": row["name"], "path": "".join(paths),
            "marker_x": marker_x, "marker_y": marker_y,
        })
    grid_lines = (
        [[project(lon, lat) for lon in range(122, 155)] for lat in range(20, 51, 5)]
        + [[project(lon, lat) for lat in range(20, 51)] for lon in range(125, 156, 5)]
    )
    return {
        "source": "日本国土交通省 国土数值信息 N03 行政区域数据（2026 年版，加工）",
        "source_url": MAP_URL, "license": "CC BY 4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "usage_note": "都道府县合并、边界简化及投影转换；游戏示意图",
        "projection": "Equirectangular, standard parallel 35", "view_box": "0 0 1000 700",
        "regions": regions, "grid": ["M" + "L".join(f"{x},{y}" for x, y in points) for points in grid_lines],
    }


def write_snapshot(path: Path, dataset: dict, source_path: Path) -> None:
    """记录来源摘要及下载时间，以 UTF-8 原子替换已生成快照。"""
    with source_path.open("rb") as source:
        digest = hashlib.sha256()
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    dataset.update(source_sha256=digest.hexdigest(), retrieved_at=datetime.now(timezone.utc).isoformat())
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(dataset, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> None:
    """从本地官方人口表及 GeoJSON 更新日本快照，不修改每日结果。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--population", type=Path, required=True, help="厚生劳动省 2025 年确定数 Excel 统计表")
    parser.add_argument("--map", type=Path, required=True, help="N03 2026 年都道府县 GeoJSON")
    args = parser.parse_args()
    population = read_population(args.population)
    japan_map = prepare_map(args.map, population)
    write_snapshot(DATA_DIR / "japan_population.json", population, args.population)
    write_snapshot(DATA_DIR / "japan_map.json", japan_map, args.map)
    print("已更新日本人口及 SVG 地图：47 个都道府县")


if __name__ == "__main__":
    main()
