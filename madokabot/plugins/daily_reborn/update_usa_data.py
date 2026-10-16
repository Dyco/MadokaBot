"""手动将 CDC 出生统计网页与人口普查局州界 KML 转为美国投胎快照，地图处理需安装 data 可选依赖。"""

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from bs4 import BeautifulSoup
from shapely.geometry import Polygon

DATA_DIR = Path(__file__).parent / "data"
POPULATION_URL = "https://www.cdc.gov/nchs/fastats/state-and-territorial-data.htm"
MAP_URL = "https://www2.census.gov/geo/tiger/GENZ2025/kml/cb_2025_us_state_20m.zip"
XML = {"k": "http://www.opengis.net/kml/2.2"}
# 使用州邮政缩写连接人口与地图，华盛顿特区单独作为一个地区。
STATE_NAMES = {
    "AL": "阿拉巴马州", "AK": "阿拉斯加州", "AZ": "亚利桑那州", "AR": "阿肯色州",
    "CA": "加利福尼亚州", "CO": "科罗拉多州", "CT": "康涅狄格州", "DE": "特拉华州",
    "DC": "华盛顿哥伦比亚特区", "FL": "佛罗里达州", "GA": "佐治亚州", "HI": "夏威夷州",
    "ID": "爱达荷州", "IL": "伊利诺伊州", "IN": "印第安纳州", "IA": "艾奥瓦州",
    "KS": "堪萨斯州", "KY": "肯塔基州", "LA": "路易斯安那州", "ME": "缅因州",
    "MD": "马里兰州", "MA": "马萨诸塞州", "MI": "密歇根州", "MN": "明尼苏达州",
    "MS": "密西西比州", "MO": "密苏里州", "MT": "蒙大拿州", "NE": "内布拉斯加州",
    "NV": "内华达州", "NH": "新罕布什尔州", "NJ": "新泽西州", "NM": "新墨西哥州",
    "NY": "纽约州", "NC": "北卡罗来纳州", "ND": "北达科他州", "OH": "俄亥俄州",
    "OK": "俄克拉何马州", "OR": "俄勒冈州", "PA": "宾夕法尼亚州", "RI": "罗得岛州",
    "SC": "南卡罗来纳州", "SD": "南达科他州", "TN": "田纳西州", "TX": "得克萨斯州",
    "UT": "犹他州", "VT": "佛蒙特州", "VA": "弗吉尼亚州", "WA": "华盛顿州",
    "WV": "西弗吉尼亚州", "WI": "威斯康星州", "WY": "怀俄明州",
}


def read_states(archive_path: Path) -> dict:
    """读取 50 州与特区的边界及英文名称，接续跨日期线的阿拉斯加岛屿。"""
    with ZipFile(archive_path) as archive:
        filename = next(name for name in archive.namelist() if name.endswith(".kml"))
        source = ET.fromstring(archive.read(filename).decode("utf-8"))
    states = {}
    for feature in source.findall(".//k:Placemark", XML):
        properties = {item.get("name"): item.text for item in feature.findall(".//k:SimpleData", XML)}
        code = properties["STUSPS"]
        if code not in STATE_NAMES:
            continue
        polygons = []
        for polygon in feature.findall(".//k:Polygon", XML):
            rings = []
            for coordinates in polygon.findall(".//k:LinearRing/k:coordinates", XML):
                points = []
                for point in coordinates.text.split():
                    longitude, latitude = map(float, point.split(",")[:2])
                    if code == "AK" and longitude > 0:
                        longitude -= 360
                    points.append((longitude, latitude))
                rings.append(points)
            polygons.append(Polygon(rings[0], rings[1:]))
        states[code] = {"name_en": properties["NAME"], "polygons": polygons}
    if set(states) != set(STATE_NAMES):
        raise ValueError("美国地图必须覆盖 50 州及华盛顿特区")
    return states


def read_population(path: Path, states: dict) -> dict:
    """从 CDC 2024 年州级表提取出生人数，性别统一使用明确标注的游戏近似值。"""
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    names = {state["name_en"] for state in states.values()}
    births_by_name = {}
    for row in soup.select("table tr"):
        cells = [cell.get_text(" ", strip=True) for cell in row.select("th,td")]
        if len(cells) == 6 and cells[0] in names:
            births_by_name[cells[0]] = int(cells[1].replace(",", ""))
    countries = []
    for code, name in STATE_NAMES.items():
        births = births_by_name[states[code]["name_en"]]
        if births <= 0:
            raise ValueError(f"美国出生人数无效：{name}")
        countries.append({
            "code": f"US-{code}", "name": name, "births": births,
            "sex_ratio": 105, "sex_ratio_estimated": True,
        })
    return {
        "source": "美国 CDC / NCHS 2024 年州级出生统计", "source_url": POPULATION_URL, "year": 2024,
        "births_note": "按母亲居住地统计；性别按约 105:100 模拟；地图点位为游戏示意",
        "gender_source": "游戏近似设定，每 100 名女婴约对应 105 名男婴", "countries": countries,
    }


def prepare_map(states: dict) -> dict:
    """将简化州界投影为现有卡片使用的离线 SVG 路径，保留阿拉斯加和夏威夷。"""
    cosine = math.cos(math.radians(35))
    points = [point for state in states.values() for polygon in state["polygons"] for point in polygon.exterior.coords]
    left, right = min(lon for lon, _ in points) * cosine, max(lon for lon, _ in points) * cosine
    top, bottom = -max(lat for _, lat in points), -min(lat for _, lat in points)
    scale = min(952 / (right - left), 660 / (bottom - top))
    offset_x = 24 + (952 - (right - left) * scale) / 2
    offset_y = 20 + (660 - (bottom - top) * scale) / 2

    def project(longitude: float, latitude: float) -> tuple[float, float]:
        """以北纬 35 度作等距圆柱投影，统一边界、定位与网格坐标。"""
        return round(offset_x + (longitude * cosine - left) * scale, 3), round(offset_y + (-latitude - top) * scale, 3)

    regions = []
    for code, name in STATE_NAMES.items():
        polygons = states[code]["polygons"]
        paths = []
        for polygon in polygons:
            for ring in (polygon.exterior, *polygon.interiors):
                projected = [project(*point) for point in ring.coords]
                paths.append("M" + "L".join(f"{x},{y}" for x, y in projected) + "Z")
        anchor = max(polygons, key=lambda polygon: polygon.area).representative_point()
        marker_x, marker_y = project(anchor.x, anchor.y)
        regions.append({
            "code": f"US-{code}", "name": name, "path": "".join(paths),
            "marker_x": marker_x, "marker_y": marker_y,
        })
    grid_lines = (
        [[project(lon, lat) for lon in range(-190, -59)] for lat in range(20, 81, 10)]
        + [[project(lon, lat) for lat in range(15, 81)] for lon in range(-180, -59, 15)]
    )
    return {
        "source": "美国人口普查局 2025 年简化州界（1:20,000,000，加工）", "source_url": MAP_URL,
        "license": "Public domain", "usage_note": "坐标投影及阿拉斯加日期线接续；游戏示意图",
        "projection": "Equirectangular, standard parallel 35", "view_box": "0 0 1000 700",
        "regions": regions, "grid": ["M" + "L".join(f"{x},{y}" for x, y in points) for points in grid_lines],
    }


def write_snapshot(path: Path, dataset: dict, source_path: Path) -> None:
    """保存来源摘要和生成时间，以 UTF-8 原子替换离线快照。"""
    dataset.update(
        source_sha256=hashlib.sha256(source_path.read_bytes()).hexdigest(),
        retrieved_at=datetime.now(timezone.utc).isoformat(),
    )
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(dataset, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> None:
    """从本地 CDC 网页和 Census 州界压缩包生成快照，不修改已有投胎结果。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--population", type=Path, required=True, help="CDC 2024 年州级出生统计网页")
    parser.add_argument("--map", type=Path, required=True, help="Census 2025 年简化州界 KML 压缩包")
    args = parser.parse_args()
    states = read_states(args.map)
    population = read_population(args.population, states)
    usa_map = prepare_map(states)
    write_snapshot(DATA_DIR / "usa_population.json", population, args.population)
    write_snapshot(DATA_DIR / "usa_map.json", usa_map, args.map)
    print("已更新美国人口及 SVG 地图：50 州及华盛顿特区")


if __name__ == "__main__":
    main()
