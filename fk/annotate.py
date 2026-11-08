"""在截图上叠加矩形 / 椭圆 / 实心箭头。

全部自己光栅化（不依赖图片库），并且**带抗锯齿**：
每个形状先算一张「覆盖度遮罩」，再按覆盖度与底图混合，边缘因此是平滑的。
"""
from __future__ import annotations

import math

from .capture import RawImage

Color = tuple[int, int, int]
Mask = dict  # {(x, y): 覆盖度 0~1}


# ---------------------------------------------------------------- 基础
def _blend(image: RawImage, x: int, y: int, color: Color, alpha: float) -> None:
    if alpha <= 0:
        return
    if not (0 <= x < image.width and 0 <= y < image.height):
        return
    offset = (y * image.width + x) * 3
    data = image.data
    if alpha >= 0.998:
        data[offset] = color[0]
        data[offset + 1] = color[1]
        data[offset + 2] = color[2]
        return
    keep = 1.0 - alpha
    data[offset] = int(data[offset] * keep + color[0] * alpha + 0.5)
    data[offset + 1] = int(data[offset + 1] * keep + color[1] * alpha + 0.5)
    data[offset + 2] = int(data[offset + 2] * keep + color[2] * alpha + 0.5)


def _composite(image: RawImage, mask: Mask, color: Color) -> None:
    for (px, py), coverage in mask.items():
        _blend(image, px, py, color, coverage)


def _add_dot(mask: Mask, cx: float, cy: float, radius: float) -> None:
    """在遮罩里放一个抗锯齿圆点（同一像素取最大覆盖度，避免重叠变黑）。"""
    radius = max(0.35, radius)
    x0 = int(math.floor(cx - radius - 1))
    x1 = int(math.ceil(cx + radius + 1))
    y0 = int(math.floor(cy - radius - 1))
    y1 = int(math.ceil(cy + radius + 1))
    edge = radius + 0.5
    for py in range(y0, y1 + 1):
        dy = py + 0.5 - cy
        for px in range(x0, x1 + 1):
            dx = px + 0.5 - cx
            distance = math.hypot(dx, dy)
            coverage = edge - distance
            if coverage <= 0:
                continue
            if coverage > 1.0:
                coverage = 1.0
            key = (px, py)
            if coverage > mask.get(key, 0.0):
                mask[key] = coverage


def _add_segment(mask: Mask, x1, y1, x2, y2, half: float) -> None:
    length = math.hypot(x2 - x1, y2 - y1)
    steps = max(1, int(length))  # 每 1 像素放一个圆点，圆点重叠足够连续
    for index in range(steps + 1):
        t = index / steps
        _add_dot(mask, x1 + (x2 - x1) * t, y1 + (y2 - y1) * t, half)


def _add_triangle(mask: Mask, p1, p2, p3) -> None:
    """三角形填充，每像素 4 点采样求覆盖度。"""
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3
    min_x = int(math.floor(min(x1, x2, x3)))
    max_x = int(math.ceil(max(x1, x2, x3)))
    min_y = int(math.floor(min(y1, y2, y3)))
    max_y = int(math.ceil(max(y1, y2, y3)))
    area = (y2 - y3) * (x1 - x3) + (x3 - x2) * (y1 - y3)
    if area == 0:
        return

    samples = (0.25, 0.75)
    for py in range(min_y, max_y + 1):
        for px in range(min_x, max_x + 1):
            hits = 0
            for sy in samples:
                for sx in samples:
                    qx = px + sx
                    qy = py + sy
                    w1 = ((y2 - y3) * (qx - x3) + (x3 - x2) * (qy - y3)) / area
                    w2 = ((y3 - y1) * (qx - x3) + (x1 - x3) * (qy - y3)) / area
                    w3 = 1.0 - w1 - w2
                    if w1 >= 0 and w2 >= 0 and w3 >= 0:
                        hits += 1
            if hits:
                key = (px, py)
                coverage = hits / 4.0
                if coverage > mask.get(key, 0.0):
                    mask[key] = coverage


# ---------------------------------------------------------------- 形状
def line(image: RawImage, x1, y1, x2, y2, color: Color, width: int = 1) -> None:
    half = max(0.4, max(1, int(width)) / 2.0)
    mask: Mask = {}
    _add_segment(mask, float(x1), float(y1), float(x2), float(y2), half)
    _composite(image, mask, color)


def rect(image: RawImage, x1, y1, x2, y2, color: Color, width: int = 1) -> None:
    left, right = sorted((float(x1), float(x2)))
    top, bottom = sorted((float(y1), float(y2)))
    half = max(0.4, max(1, int(width)) / 2.0)
    mask: Mask = {}
    _add_segment(mask, left, top, right, top, half)
    _add_segment(mask, left, bottom, right, bottom, half)
    _add_segment(mask, left, top, left, bottom, half)
    _add_segment(mask, right, top, right, bottom, half)
    _composite(image, mask, color)


def ellipse(image: RawImage, x1, y1, x2, y2, color: Color, width: int = 1) -> None:
    left, right = sorted((float(x1), float(x2)))
    top, bottom = sorted((float(y1), float(y2)))
    half = max(0.4, max(1, int(width)) / 2.0)
    cx = (left + right) / 2.0
    cy = (top + bottom) / 2.0
    rx = (right - left) / 2.0
    ry = (bottom - top) / 2.0

    mask: Mask = {}
    if rx < 0.5 or ry < 0.5:
        _add_dot(mask, cx, cy, half)
        _composite(image, mask, color)
        return

    # 拉马努金周长近似，保证采样间距 ≤ 0.5 像素
    perimeter = math.pi * (
        3 * (rx + ry) - math.sqrt(max(0.0, (3 * rx + ry) * (rx + 3 * ry)))
    )
    steps = max(48, min(20000, int(perimeter * 2)))
    for index in range(steps):
        angle = 2 * math.pi * index / steps
        _add_dot(mask, cx + rx * math.cos(angle), cy + ry * math.sin(angle), half)
    _composite(image, mask, color)


def head_points(x1, y1, x2, y2, width: int = 1) -> list[tuple[float, float]]:
    """箭头尖 + 两个底角（画布预览和光栅化共用）。"""
    start_x, start_y = float(x1), float(y1)
    end_x, end_y = float(x2), float(y2)
    delta_x = end_x - start_x
    delta_y = end_y - start_y
    length = math.hypot(delta_x, delta_y)
    thickness = max(1, int(width))
    if length < 1:
        return [(end_x, end_y), (end_x, end_y), (end_x, end_y)]

    head = min(length * 0.55, max(12.0, thickness * 4.0))
    half = head * 0.5
    unit_x = delta_x / length
    unit_y = delta_y / length
    base_x = end_x - unit_x * head
    base_y = end_y - unit_y * head
    normal_x = -unit_y
    normal_y = unit_x
    return [
        (end_x, end_y),
        (base_x + normal_x * half, base_y + normal_y * half),
        (base_x - normal_x * half, base_y - normal_y * half),
    ]


def arrow(image: RawImage, x1, y1, x2, y2, color: Color, width: int = 1) -> None:
    """实心箭头：起点是尾部，终点是箭头尖。"""
    thickness = max(1, int(width))
    half = max(0.4, thickness / 2.0)
    start_x, start_y = float(x1), float(y1)
    end_x, end_y = float(x2), float(y2)
    length = math.hypot(end_x - start_x, end_y - start_y)

    mask: Mask = {}
    if length < 1:
        _add_dot(mask, start_x, start_y, max(0.8, half))
        _composite(image, mask, color)
        return

    tip, left, right = head_points(x1, y1, x2, y2, width)
    base_x = (left[0] + right[0]) / 2.0
    base_y = (left[1] + right[1]) / 2.0

    # 箭杆画到三角形底边中点再往尖端挪一点，避免接缝
    _add_segment(
        mask,
        start_x,
        start_y,
        base_x * 0.45 + tip[0] * 0.55,
        base_y * 0.45 + tip[1] * 0.55,
        half,
    )
    _add_triangle(mask, tip, left, right)
    _composite(image, mask, color)


def apply_shape(image: RawImage, shape: dict) -> None:
    """按形状字典把标注画到图片上。"""
    if not shape:
        return
    kind = str(shape.get("kind", ""))
    color = tuple(shape.get("color", (255, 0, 0)))  # type: ignore[arg-type]
    width = int(shape.get("width", 2) or 2)
    x1, y1 = shape.get("x1", 0), shape.get("y1", 0)
    x2, y2 = shape.get("x2", 0), shape.get("y2", 0)

    if kind == "rect":
        rect(image, x1, y1, x2, y2, color, width)
    elif kind == "ellipse":
        ellipse(image, x1, y1, x2, y2, color, width)
    elif kind == "arrow":
        arrow(image, x1, y1, x2, y2, color, width)


def render(image: RawImage, shapes: list[dict]) -> RawImage:
    """返回画好所有标注的新图片。"""
    result = image.copy()
    for shape in shapes or []:
        apply_shape(result, shape)
    return result
