"""离线地图几何、出生地定位与局部取景。"""

import math
import random
import re
from functools import lru_cache

from .modes import RebornMode
from .resources import load_json_resource


@lru_cache(maxsize=1)
def load_world_map() -> list[dict]:
    """通过核心 JSON 工具读取地图，台湾、香港、澳门与中国共用高亮编号。"""
    return load_json_resource("world_map.json")["regions"]


@lru_cache(maxsize=3)
def load_regional_map(mode: RebornMode) -> dict:
    """通过核心 JSON 工具读取各国家模式的 SVG 路径及地区定位。"""
    return load_json_resource(f"{mode}_map.json")


@lru_cache(maxsize=300)
def map_polygons(path: str) -> tuple:
    """解析离线 M/L/Z 坐标并剔除退化环，避免把单点或线段当作陆地。"""
    polygons = []
    for ring in path.split("M"):
        points = tuple((float(x), float(y)) for x, y in re.findall(r"(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)", ring))
        if not points:
            continue
        x, y = points[0]
        area = sum((ax - x) * (by - y) - (bx - x) * (ay - y)
                   for (ax, ay), (bx, by) in zip(points, points[1:] + points[:1]))
        if abs(area) > 1e-12:
            polygons.append(points)
    return tuple(polygons)


def polygon_distance(points: tuple, x: float, y: float) -> float:
    """计算定位点到多边形的距离平方，落在内部时优先选择该区域。"""
    inside = False
    distance = float("inf")
    for (ax, ay), (bx, by) in zip(points, points[1:] + points[:1]):
        if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
            inside = not inside
        dx, dy = bx - ax, by - ay
        length = dx * dx + dy * dy
        ratio = max(0, min(1, ((x - ax) * dx + (y - ay) * dy) / length)) if length else 0
        distance = min(distance, (x - ax - ratio * dx) ** 2 + (y - ay - ratio * dy) ** 2)
    return 0 if inside else distance


def local_polygons(path: str, x: float, *, mode: RebornMode) -> tuple:
    """将跨日期变更线的岛屿移到定位点附近，统一抽点与局部取景坐标。"""
    polygons = []
    for points in map_polygons(path):
        center = (min(px for px, _ in points) + max(px for px, _ in points)) / 2
        offset = round((x - center) / 1000) * 1000 if mode == "world" else 0
        polygons.append(tuple((px + offset, py) for px, py in points))
    return tuple(polygons)


def contains_point(polygons: tuple, x: float, y: float) -> bool:
    """按 SVG 奇偶填充规则判断陆地内部，边界与内部空洞均不接受。"""
    inside = False
    for points in polygons:
        for (ax, ay), (bx, by) in zip(points, points[1:] + points[:1]):
            cross = (x - ax) * (by - ay) - (y - ay) * (bx - ax)
            if abs(cross) < 1e-10 and min(ax, bx) <= x <= max(ax, bx) and min(ay, by) <= y <= max(ay, by):
                return False
            if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
                inside = not inside
    return inside


@lru_cache(maxsize=600)
def interior_anchor(path: str, x: float, y: float, *, mode: RebornMode) -> tuple[float, float]:
    """纠正落在海面或粗略边界外的原始定位，以扫描线寻找稳定内点。"""
    polygons = local_polygons(path, x, mode=mode)
    if contains_point(polygons, x, y):
        return x, y
    nearest = min(polygons, key=lambda points: polygon_distance(points, x, y))
    levels = sorted({py for _, py in nearest})
    scanlines = sorted(((a + b) / 2 for a, b in zip(levels, levels[1:])), key=lambda level: abs(level - y))
    for level in scanlines:
        crossings = sorted(
            ax + (bx - ax) * (level - ay) / (by - ay)
            for points in polygons for (ax, ay), (bx, by) in zip(points, points[1:] + points[:1])
            if (ay > level) != (by > level)
        )
        candidates = [
            (max(left + (right - left) / 4, min(x, right - (right - left) / 4)), level)
            for left, right in zip(crossings[::2], crossings[1::2]) if right - left > 1e-8
        ]
        for point in sorted(candidates, key=lambda point: (point[0] - x) ** 2):
            if contains_point(polygons, *point):
                return point
    raise ValueError("出生地区地图没有可用的陆地内点")


def birth_region(country: dict, *, mode: RebornMode) -> tuple[dict, float, float]:
    """定位出生地理单元，区域模式使用细分边界，世界模式排除非军事区。"""
    if mode != "world":
        region = next(row for row in load_regional_map(mode)["regions"] if row["code"] == country["code"])
        return region, region["marker_x"], region["marker_y"]
    x, y = (country["longitude"] + 180) * 1000 / 360, (85 - country["latitude"]) * 1000 / 360
    candidates = [
        row for row in load_world_map()
        if row["code"] == country["map_code"] and row.get("birth_area", True) and map_polygons(row["path"])
    ]
    if len(candidates) == 1:
        return candidates[0], x, y
    region = min(candidates, key=lambda row: min(
        polygon_distance(points, x, y) for points in local_polygons(row["path"], x, mode="world")
    ))
    return region, x, y


def random_location(country: dict, *, mode: RebornMode) -> dict:
    """在出生地区内做有限幅度随机偏移，拒绝越界，抽样耗尽则使用安全内点。"""
    region, x, y = birth_region(country, mode=mode)
    polygons = local_polygons(region["path"], x, mode=mode)
    anchor_x, anchor_y = interior_anchor(region["path"], x, y, mode=mode)
    nearest = min(polygons, key=lambda points: polygon_distance(points, anchor_x, anchor_y))
    radius_x = (max(px for px, _ in nearest) - min(px for px, _ in nearest)) * .12
    radius_y = (max(py for _, py in nearest) - min(py for _, py in nearest)) * .12
    for _ in range(128):
        px = random.uniform(anchor_x - radius_x, anchor_x + radius_x)
        py = random.uniform(anchor_y - radius_y, anchor_y + radius_y)
        if contains_point(polygons, px, py):
            return {"x": px, "y": py}
    return {"x": anchor_x, "y": anchor_y}


def result_location(result: dict) -> tuple[dict, float, float]:
    """优先读取保存的定位；缺少坐标或底图更新后越界时使用地区内的固定安全点。"""
    mode = result.get("mode", "world")
    region, x, y = birth_region(result["country"], mode=mode)
    point = result.get("map_point")
    if point and all(isinstance(point.get(key), (int, float)) and math.isfinite(point[key]) for key in ("x", "y")):
        if contains_point(local_polygons(region["path"], x, mode=mode), point["x"], point["y"]):
            return region, point["x"], point["y"]
    return region, *interior_anchor(region["path"], x, y, mode=mode)


def focused_map(region: dict, x: float, y: float, *, mode: RebornMode) -> tuple[str, float, list[int]]:
    """按陆地区块取景，仅限制已确认过宽的世界地区，跨日期线接续底图。"""
    polygons = local_polygons(region["path"], x, mode=mode)
    # 同时覆盖定位点，避免较粗的世界地图把小岛国或微型地区的标记裁掉。
    nearest = min(polygons, key=lambda points: polygon_distance(points, x, y))
    left, right = min(x, *(px for px, _ in nearest)), max(x, *(px for px, _ in nearest))
    top, bottom = min(y, *(py for _, py in nearest)), max(y, *(py for _, py in nearest))
    minimum = 6 if mode == "world" else 12
    margin = max(right - left, bottom - top, minimum) * .35
    nearby = [
        (px, py) for points in polygons for px, py in points
        if left - margin <= px <= right + margin and top - margin <= py <= bottom + margin
    ]
    left, right = min(left, *(px for px, _ in nearby)), max(right, *(px for px, _ in nearby))
    top, bottom = min(top, *(py for _, py in nearby)), max(bottom, *(py for _, py in nearby))
    # 各模式统一扩大取景范围，保留更多周边地理参照。
    width = max((right - left) * 1.3, (bottom - top) * 1.3 * 1000 / 560, minimum) * 2.7
    center_x, center_y = (left + right) / 2, (top + bottom) / 2
    limit_wide_view = mode == "world" and region["code"] in {"RUS", "USA", "CAN", "GRL"} and width > 520
    if limit_wide_view:
        width = 520
        center_x, center_y = x, y
    height = width * 560 / 1000
    start_x, start_y = center_x - width / 2, center_y - height / 2
    if limit_wide_view:
        # 仅对过宽地区收掉纬度方向的空白，其他地区沿用原有取景。
        start_y = max(0, min(start_y, 440 - height))
    offsets = [0]
    if mode == "world":
        offsets = ([-1000] if start_x < 0 else []) + offsets + ([1000] if start_x + width > 1000 else [])
    return f"{start_x:.4f} {start_y:.4f} {width:.4f} {height:.4f}", width / 1000, offsets


