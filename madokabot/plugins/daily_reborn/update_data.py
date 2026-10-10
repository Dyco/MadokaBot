"""手动更新人口快照与地图：直接运行本文件，不需启动机器人。"""

import argparse
import json
import math
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import httpx

DATA_DIR = Path(__file__).parent / "data"
POPULATION_URL = (
    "https://population.un.org/wpp/assets/Excel%20Files/1_Indicator%20(Standard)/"
    "EXCEL_FILES/1_General/WPP2024_GEN_F01_DEMOGRAPHIC_INDICATORS_COMPACT.xlsx"
)
MAP_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/"
    "geojson/ne_10m_admin_0_map_units.geojson"
)
XML = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
MAP_ALIASES = {
    "TWN": "CHN", "HKG": "CHN", "MAC": "CHN",
    "SOL": "SOM", "CYN": "CYP", "KOS": "XKX",
}
CHINESE_NAMES = {
    "CHN": "中国内地", "TWN": "中国台湾", "HKG": "中国香港",
    "MAC": "中国澳门", "GBR": "英国",
}


def read_cells(row: ET.Element, strings: list[str]) -> dict[str, str]:
    """读取工作表行，保留列编号并展开共享字符串。"""
    values = {}
    for cell in row:
        value = cell.find("m:v", XML)
        text = value.text if value is not None else ""
        if cell.get("t") == "s":
            text = strings[int(text)]
        values["".join(c for c in cell.get("r") if c.isalpha())] = text
    return values


def read_population(workbook: Path, year: int) -> list[dict]:
    """从联合国中方案工作表提取指定年份，保留所有有 ISO3 编号的国家和地区。"""
    with ZipFile(workbook) as archive:
        strings = ["".join(node.itertext()) for node in ET.fromstring(archive.read("xl/sharedStrings.xml"))]
        book = ET.fromstring(archive.read("xl/workbook.xml"))
        sheet = next(s for s in book.find("m:sheets", XML) if s.get("name") == "Medium variant")
        relation_id = sheet.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        relations = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        target = next(r.get("Target") for r in relations if r.get("Id") == relation_id)
        target = target.lstrip("/") if target.startswith("/") else "xl/" + target
        columns = {}
        countries = []
        with archive.open(target) as source:
            for _, row in ET.iterparse(source, events=("end",)):
                if row.tag != f"{{{XML['m']}}}row":
                    continue
                cells = read_cells(row, strings)
                if "Year" in cells.values():
                    columns = {value: key for key, value in cells.items()}
                elif columns and cells.get(columns["Year"]) == str(year):
                    code = cells.get(columns["ISO3 Alpha-code"], "")
                    if len(code) == 3:
                        countries.append({
                            "code": code,
                            "births": float(cells[columns["Births (thousands)"]]) * 1000,
                            "birth_rate": float(cells[columns["Crude Birth Rate (births per 1,000 population)"]]),
                            "sex_ratio": float(cells[columns["Sex Ratio at Birth (males per 100 female births)"]]),
                        })
                row.clear()
    if len(countries) < 230 or len({c["code"] for c in countries}) != len(countries):
        raise ValueError(f"{year} 年人口数据不完整：{len(countries)} 个国家/地区")
    if any(
        not math.isfinite(c[key]) or c[key] <= 0
        for c in countries for key in ("births", "birth_rate", "sex_ratio")
    ):
        raise ValueError("出生人数、出生率或出生性别比存在无效值")
    return countries


def simplify_ring(points: list, tolerance: float = 0.06) -> list:
    """用道格拉斯普克算法压缩地图轮廓，保留每个岛屿的闭合边界。"""
    if len(points) <= 4:
        return points
    start, end = points[0], points[-1]
    dx, dy = end[0] - start[0], end[1] - start[1]
    length_squared = dx * dx + dy * dy
    distances = []
    for x, y in points[1:-1]:
        ratio = 0
        if length_squared:
            ratio = max(0, min(1, ((x - start[0]) * dx + (y - start[1]) * dy) / length_squared))
        distances.append((x - start[0] - ratio * dx) ** 2 + (y - start[1] - ratio * dy) ** 2)
    distance = max(distances)
    if distance <= tolerance * tolerance:
        return [start, end]
    split = distances.index(distance) + 1
    return simplify_ring(points[:split + 1], tolerance)[:-1] + simplify_ring(points[split:], tolerance)


def prepare_map(world: dict) -> tuple[list[dict], dict]:
    """将公开地图转换为 SVG 路径，统一中国各地区的高亮范围。"""
    regions = []
    locations = {}
    for feature in world["features"]:
        props = feature["properties"]
        code = props["ISO_A3_EH"]
        if code == "-99":
            code = props["ADM0_A3"]
        if code == "ATA":
            continue
        map_code = MAP_ALIASES.get(code, code)
        location = {
            "map_code": map_code,
            "name": CHINESE_NAMES.get(code, props["NAME_ZH"]),
            "longitude": props["LABEL_X"],
            "latitude": props["LABEL_Y"],
        }
        location_code = map_code if code == "KOS" else code
        # 同一国家可能拆成多个地理单元，避免离岛覆盖主区域的名称与定位。
        locations.setdefault(location_code, location)
        if props["GU_A3"] == "ENG":
            locations[location_code] = location
        geometry = feature["geometry"]
        polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
        paths = []
        for polygon in polygons:
            for ring in polygon:
                points = simplify_ring(ring)
                if len(points) < 4:
                    points = ring
                paths.append("M" + "L".join(
                    f"{(lon + 180) * 1000 / 360:.2f},{(85 - lat) * 1000 / 360:.2f}" for lon, lat in points
                ) + "Z")
        regions.append({"code": map_code, "path": "".join(paths)})
    return regions, locations


def write_json(path: Path, value: dict) -> None:
    """先写入临时文件再替换，避免中断更新损坏已有资源。"""
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> None:
    """下载或复用原始文件，校验后更新插件附带的离线数据。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=datetime.now(timezone.utc).year)
    parser.add_argument("--workbook", type=Path)
    parser.add_argument("--map", type=Path)
    args = parser.parse_args()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    # 原始下载使用临时目录，正式资源只保存所需年份与地图路径。
    with tempfile.TemporaryDirectory() as temporary:
        workbook = args.workbook
        if workbook is None:
            workbook = Path(temporary) / "wpp.xlsx"
            with httpx.stream("GET", POPULATION_URL, follow_redirects=True, timeout=120) as response:
                response.raise_for_status()
                with workbook.open("wb") as output:
                    for chunk in response.iter_bytes():
                        output.write(chunk)
        if args.map:
            world = json.loads(args.map.read_text(encoding="utf-8"))
        else:
            response = httpx.get(MAP_URL, follow_redirects=True, timeout=120)
            response.raise_for_status()
            world = response.json()
        regions, locations = prepare_map(world)
        countries = read_population(workbook, args.year)
        missing = [country["code"] for country in countries if country["code"] not in locations]
        if missing:
            raise ValueError(f"地图缺少地区定位：{missing}")
        for country in countries:
            country.update(locations[country["code"]])
        metadata = {
            "source": "UN WPP 2024（2025 更新）",
            "source_url": POPULATION_URL,
            "license": "CC BY 3.0 IGO",
            "year": args.year,
            "variant": "Medium",
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "countries": countries,
        }
        write_json(DATA_DIR / "population.json", metadata)
        write_json(DATA_DIR / "world_map.json", {"source_url": MAP_URL, "license": "Public domain", "regions": regions})
        print(f"已更新 {args.year} 年数据：{len(countries)} 个国家/地区，年出生人数 {sum(c['births'] for c in countries):,.0f}")


if __name__ == "__main__":
    main()
