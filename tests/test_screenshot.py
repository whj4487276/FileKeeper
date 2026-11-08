"""快速截图相关逻辑自测（截图抓取 / PNG 编码 / 标注绘制 / 快捷键解析）。

运行：python tests\\test_screenshot.py
"""
from __future__ import annotations

import struct
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fk import annotate as ann  # noqa: E402
from fk import capture as cap  # noqa: E402
from fk import hotkey as hk  # noqa: E402

PASSED = 0
FAILED = 0


def check(condition, message: str) -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  ok   {message}")
    else:
        FAILED += 1
        print(f"  FAIL {message}")


def test_hotkey() -> None:
    print("\n[快捷键解析]")
    parsed = hk.parse_hotkey("Ctrl+Alt+A")
    check(parsed is not None, "Ctrl+Alt+A 可解析")
    if parsed:
        modifiers, vk = parsed
        check(bool(modifiers & hk.MOD_CONTROL), "含 Ctrl")
        check(bool(modifiers & hk.MOD_ALT), "含 Alt")
        check(vk == ord("A"), f"键为 A（{vk}）")
        check(modifiers & hk.MOD_NOREPEAT, "带 NOREPEAT，长按不会连发")
        check(hk.format_hotkey(modifiers, vk) == "Ctrl+Alt+A", "格式化可还原")

    check(hk.parse_hotkey("ctrl+shift+f5") is not None, "小写 + F5 也能解析")
    check(hk.parse_hotkey("A") is None, "没有修饰键 → 无效")
    check(hk.parse_hotkey("Ctrl+") is None, "缺少主键 → 无效")
    check(hk.parse_hotkey("Ctrl+Alt+Nope") is None, "未知键名 → 无效")
    check(hk.parse_hotkey("") is None, "空字符串 → 无效")

    event = hk.from_tk_event("a", 0x0004)
    check(event is not None and event[1] == ord("A"), "tk 事件 Ctrl+A 可转换")
    check(hk.from_tk_event("Control_L", 0x0004) is None, "单独的修饰键忽略")
    check(hk.from_tk_event("a", 0) is None, "无修饰键忽略")

    check(hk.format_hotkey(hk.MOD_WIN | hk.MOD_SHIFT, ord("S")) == "Shift+Win+S", "Win+Shift 组合显示")

    parsed_default = hk.parse_hotkey(hk.DEFAULT_HOTKEY)
    check(parsed_default is not None, f"默认快捷键可解析（{hk.DEFAULT_HOTKEY}）")
    check(hk.DEFAULT_HOTKEY == "Ctrl+Alt+A", "默认键是 Ctrl+Alt+A")
    for fallback in hk.FALLBACK_HOTKEYS:
        check(hk.parse_hotkey(fallback) is not None, f"备选键可解析（{fallback}）")
    check(
        "Alt+Shift+S" in hk.LEGACY_DEFAULT_HOTKEYS,
        "旧默认键会被识别并迁移",
    )


def test_image() -> None:
    print("\n[图片基础]")
    image = cap.RawImage.blank(8, 6, (10, 20, 30))
    check(image.width == 8 and image.height == 6, "尺寸正确")
    check(len(image.data) == 8 * 6 * 3, "缓冲长度 = 宽 × 高 × 3")
    check(image.pixel(0, 0) == (10, 20, 30), "默认颜色正确")

    image.put(1, 1, (200, 100, 50))
    check(image.pixel(1, 1) == (200, 100, 50), "写像素生效")
    image.put(-5, -5, (1, 2, 3))
    check(image.pixel(1, 1) == (200, 100, 50), "越界写入被忽略")

    clone = image.copy()
    clone.put(0, 0, (0, 0, 0))
    check(image.pixel(0, 0) == (10, 20, 30), "copy 是独立副本")

    check(cap.virtual_screen()[2] > 0, "能取到虚拟屏幕尺寸")


def test_png() -> None:
    print("\n[PNG 编码]")
    image = cap.RawImage.blank(16, 12, (255, 0, 0))
    data = cap.png_bytes(image)
    check(data[:8] == b"\x89PNG\r\n\x1a\n", "PNG 文件头正确")

    length = struct.unpack(">I", data[8:12])[0]
    check(data[12:16] == b"IHDR", "第一个块是 IHDR")
    width, height, depth, color_type = struct.unpack(">IIBB", data[16:26])
    check((width, height) == (16, 12), f"IHDR 尺寸正确（{width}×{height}）")
    check(depth == 8 and color_type == 2, "8 位真彩色")
    check(length == 13, "IHDR 长度正确")
    check(data[-8:-4] == b"IEND", "以 IEND 结尾")

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "shot.png"
        cap.save_png(path, image)
        check(path.exists() and path.stat().st_size > 50, f"保存文件成功（{path.stat().st_size} 字节）")
        check(path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n", "落盘内容仍是 PNG")

    check(cap.png_data_uri(image)[:2] == "iV", "base64 数据可用于 PhotoImage")


def test_grab() -> None:
    print("\n[屏幕抓取]")
    grabbed = cap.grab_screen(0, 0, 40, 30)
    check(grabbed is not None, "抓取屏幕区域成功")
    if grabbed:
        check((grabbed.width, grabbed.height) == (40, 30), "尺寸与请求一致")
        check(len(grabbed.data) == 40 * 30 * 3, "数据长度正确")
    check(cap.grab_screen(0, 0, 0, 10) is None, "宽为 0 返回 None")
    check(cap.grab_screen(0, 0, 10, -3) is None, "负高度返回 None")


def near(actual, target, tol: int = 70) -> bool:
    """抗锯齿会让边缘像素是混合色，这里允许一定误差。"""
    return all(abs(a - b) <= tol for a, b in zip(actual, target))


def test_draw() -> None:
    print("\n[标注绘制]")
    image = cap.RawImage.blank(100, 80, (255, 255, 255))
    ann.rect(image, 10, 10, 90, 70, (255, 0, 0), 3)
    check(near(image.pixel(50, 10), (255, 0, 0)), f"矩形上边 {image.pixel(50, 10)}")
    check(near(image.pixel(10, 40), (255, 0, 0)), f"矩形左边 {image.pixel(10, 40)}")
    check(near(image.pixel(90, 40), (255, 0, 0)), f"矩形右边 {image.pixel(90, 40)}")
    check(near(image.pixel(50, 70), (255, 0, 0)), f"矩形下边 {image.pixel(50, 70)}")
    check(image.pixel(50, 40) == (255, 255, 255), "矩形内部是空的")

    # 抗锯齿：线的上下各一像素应该是"半透明"的混合色
    above = image.pixel(50, 8)
    check(
        above != (255, 255, 255) and not near(above, (255, 0, 0), 12),
        f"线边缘有过渡像素（{above}）",
    )

    image2 = cap.RawImage.blank(100, 80, (255, 255, 255))
    ann.ellipse(image2, 10, 10, 90, 60, (0, 0, 255), 2)
    check(image2.pixel(50, 10) != (255, 255, 255), "椭圆上顶点被描边")
    check(image2.pixel(10, 35) != (255, 255, 255), "椭圆左顶点被描边")
    check(image2.pixel(50, 35) == (255, 255, 255), "椭圆内部是空的")

    # 椭圆边缘应该有多种颜色（说明做了抗锯齿，而不是硬阶梯）
    edge_colors = set()
    for x in range(20, 80):
        edge_colors.add(image2.pixel(x, 11))
    check(len(edge_colors) >= 3, f"椭圆边缘过渡颜色数 {len(edge_colors)}")

    image3 = cap.RawImage.blank(100, 80, (255, 255, 255))
    ann.arrow(image3, 10, 70, 90, 10, (0, 128, 0), 3)
    check(near(image3.pixel(10, 70), (0, 128, 0)), f"箭头尾部着色 {image3.pixel(10, 70)}")
    check(near(image3.pixel(50, 40), (0, 128, 0)), f"箭杆中段着色 {image3.pixel(50, 40)}")
    check(
        near(image3.pixel(88, 12), (0, 128, 0), 90) or near(image3.pixel(87, 13), (0, 128, 0), 90),
        f"箭头尖端是实心的 ({image3.pixel(88, 12)} / {image3.pixel(87, 13)})",
    )

    # 越界不应崩溃
    image4 = cap.RawImage.blank(30, 20, (255, 255, 255))
    ann.rect(image4, -50, -50, 100, 100, (0, 0, 0), 2)
    ann.ellipse(image4, -20, -20, 10, 10, (0, 0, 0), 2)
    ann.arrow(image4, -10, -10, 200, 200, (0, 0, 0), 4)
    check(True, "越界绘制不会抛异常")

    shapes = [
        {"kind": "rect", "x1": 5, "y1": 5, "x2": 25, "y2": 15, "color": (255, 0, 0), "width": 2},
        {"kind": "arrow", "x1": 5, "y1": 18, "x2": 25, "y2": 18, "color": (0, 0, 0), "width": 2},
    ]
    base = cap.RawImage.blank(30, 20, (255, 255, 255))
    rendered = ann.render(base, shapes)
    check(near(rendered.pixel(15, 5), (255, 0, 0)), "render 画上了矩形")
    check(near(rendered.pixel(5, 18), (0, 0, 0)), "render 画上了箭头")
    check(base.pixel(15, 5) == (255, 255, 255), "render 不修改原图")


def test_crop() -> None:
    print("\n[裁剪]")
    screen = cap.RawImage.blank(100, 60, (10, 20, 30))
    screen.put(0, 0, (255, 0, 0))
    screen.put(99, 59, (0, 255, 0))

    piece = cap.crop(screen, 0, 0, 50, 30)
    check(piece is not None and (piece.width, piece.height) == (50, 30), "裁剪尺寸正确")
    check(piece.pixel(0, 0) == (255, 0, 0), "裁剪保留左上角像素")

    corner = cap.crop(screen, 80, 40, 40, 30)
    check(corner.pixel(19, 19) == (0, 255, 0), "裁剪保留右下角像素")
    check(corner.pixel(39, 29) == (0, 0, 0), "越界部分补黑")

    outside = cap.crop(screen, -10, -10, 20, 20)
    check(outside is not None and outside.width == 20, "负坐标不崩溃")
    check(cap.crop(None, 0, 0, 10, 10) is None, "空图返回 None")


def main() -> int:
    print("=" * 60)
    print("电脑百宝箱 · 快速截图自测")
    print("=" * 60)
    test_hotkey()
    test_image()
    test_png()
    test_grab()
    test_draw()
    test_crop()
    print("\n" + "=" * 60)
    print(f"通过 {PASSED} 项，失败 {FAILED} 项")
    print("=" * 60)
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
