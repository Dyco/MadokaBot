"""手动将 DataV 省级 GeoJSON 转换为中国投胎的离线 SVG 路径。"""

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import httpx

DATA_DIR = Path(__file__).parent / "data"
MAP_URL = "https://geo.datav.aliyun.com/areas_v3/bound/100000_full.json"
NAME_ALIASES = {"中国台湾": "台湾省", "中国香港": "香港特别行政区", "中国澳门": "澳门特别行政区"}


def project(longitude: float, latitude: float) -> tuple[float, float]:
    """采用标准纬线 25°、47°的阿尔伯斯等积投影，适配中国轮廓。"""
    phi1, phi2, phi0 = map(math.radians, (25, 47, 35))
    n = (math.sin(phi1) + math.sin(phi2)) / 2
    c = math.cos(phi1) ** 2 + 2 * n * math.sin(phi1)
    rho = math.sqrt(c - 2 * n * math.sin(math.radians(latitude))) / n
    rho0 = math.sqrt(c - 2 * n * math.sin(phi0)) / n
    theta = n * math.radians(longitude - 105)
    return rho * math.sin(theta), rho * math.cos(theta) - rho0


def fit_projection(points: list, box: tuple):
    """将投影坐标等比居中放入指定画框，不改变各地区的相对形状。"""
    projected = [project(*point) for point in points]
    left, right = min(x for x, _ in projected), max(x for x, _ in projected)
    top, bottom = min(y for _, y in projected), max(y for _, y in projected)
    bx, by, width, height = box
    scale = min(width / (right - left), height / (bottom - top))
    offset_x = bx + (width - (right - left) * scale) / 2
    offset_y = by + (height - (bottom - top) * scale) / 2

    def fitted(longitude: float, latitude: float) -> tuple[float, float]:
        """返回画框内的投影位置，供边界与定位点使用同一坐标变换。"""
        x, y = project(longitude, latitude)
        return round(offset_x + (x - left) * scale, 2), round(offset_y + (y - top) * scale, 2)

    return fitted


def rings(feature: dict) -> list:
    """展开多面和面中的全部闭合环，保留岛屿与内部边界。"""
    geometry = feature["geometry"]
    if geometry["type"] not in ("Polygon", "MultiPolygon"):
        raise ValueError("中国地图存在不支持的几何类型")
    polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    return [ring for polygon in polygons for ring in polygon]


def path_for(feature: dict, projection) -> str:
    """保留原始全部顶点生成 SVG 闭合路径，不另行简化边界。"""
    paths = []
    for ring in rings(feature):
        points = [projection(*point) for point in ring]
        paths.append("M" + "L".join(f"{x},{y}" for x, y in points) + "Z")
    return "".join(paths)


def inset_projection(bounds: tuple, box: tuple):
    """按经纬度范围计算局部画框的等比投影。"""
    west, south, east, north = bounds
    return fit_projection([(lon, lat) for lon in (west, (west + east) / 2, east) for lat in (south, north)], box)


def prepare_map(source: dict, population: dict) -> dict:
    """校验完整省级覆盖并生成主图、南海诸岛附图与港澳放大图。"""
    features = source["features"]
    provinces = {f["properties"]["name"]: f for f in features if f["properties"].get("level") == "province"}
    if len(provinces) != 34:
        raise ValueError(f"中国地图省级地区数应为 34，实际为 {len(provinces)}")
    population_names = [NAME_ALIASES.get(row["name"], row["name"]) for row in population["countries"]]
    if len(population_names) != 34 or set(population_names) != set(provinces):
        raise ValueError("中国人口快照必须与地图的 34 个省级地区一一对应")
    sea = [f for f in features if f["properties"].get("adchar") == "JD"]
    if len(sea) != 1:
        raise ValueError("中国地图缺少完整断续线图层")
    points = [point for feature in provinces.values() for ring in rings(feature) for point in ring if point[1] >= 18]
    main = fit_projection(points, (24, 20, 850, 650))
    south_sea = inset_projection((105, 2.5, 125, 26), (808, 454, 158, 208))
    pearl_delta = inset_projection((112.75, 21.75, 114.65, 22.9), (42, 544, 236, 108))
    regions = []
    for row in population["countries"]:
        feature = provinces[NAME_ALIASES.get(row["name"], row["name"])]
        x, y = main(*feature["properties"]["center"])
        regions.append({
            "code": row["code"], "name": row["name"], "path": path_for(feature, main),
            "marker_x": x, "marker_y": y,
            "sea_path": path_for(feature, south_sea) if any(105 <= lon <= 125 and lat <= 26 for ring in rings(feature) for lon, lat in ring) else "",
            "detail_path": path_for(feature, pearl_delta) if row["code"] in ("CN-GD", "CN-HK", "CN-MO") else "",
        })
    return {
        "source": "阿里云 DataV.GeoAtlas（高德开放平台数据）", "source_url": MAP_URL,
        "usage_note": "供应方说明仅供学习交流；SVG 为游戏示意图，不沿用参考 JPG 的审图号。",
        "projection": "Albers equal-area, parallels 25/47, central meridian 105",
        "view_box": "0 0 1000 700", "regions": regions,
        "sea_lines": path_for(sea[0], main), "inset_sea_lines": path_for(sea[0], south_sea),
        "grid": ["M" + "L".join(f"{x},{y}" for x, y in points) for points in (
            [[main(lon, lat) for lon in range(73, 136)] for lat in (20, 30, 40, 50)]
            + [[main(lon, lat) for lat in range(18, 55)] for lon in (80, 90, 100, 110, 120, 130)]
        )],
    }


def main() -> None:
    """下载或复用 GeoJSON，校验完成后原子替换地图，不修改人口和每日结果。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", type=Path, help="复用已下载的 DataV GeoJSON")
    args = parser.parse_args()
    if args.map:
        content = args.map.read_bytes()
    else:
        response = httpx.get(MAP_URL, follow_redirects=True, timeout=60)
        response.raise_for_status()
        content = response.content
    source = json.loads(content.decode("utf-8"))
    population = json.loads((DATA_DIR / "china_population.json").read_text(encoding="utf-8"))
    result = prepare_map(source, population)
    result.update(source_sha256=hashlib.sha256(content).hexdigest(), retrieved_at=datetime.now(timezone.utc).isoformat())
    path = DATA_DIR / "china_map.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    temporary.replace(path)
    print(f"已更新中国 SVG 地图：{len(result['regions'])} 个省级地区，含南海诸岛附图与港澳放大图")


if __name__ == "__main__":
    main()
