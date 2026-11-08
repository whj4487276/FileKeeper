"""屏幕截图（GDI BitBlt）与无依赖 PNG 编码。"""
from __future__ import annotations

import ctypes
import struct
import zlib
from ctypes import wintypes
from dataclasses import dataclass

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
try:
    dwmapi = ctypes.windll.dwmapi
except Exception:  # pragma: no cover - 极老系统
    dwmapi = None
kernel32 = ctypes.windll.kernel32

SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0
BI_RGB = 0

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


user32.GetDC.restype = wintypes.HDC
user32.GetDC.argtypes = [wintypes.HWND]
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.SelectObject.restype = ctypes.c_void_p
gdi32.SelectObject.argtypes = [wintypes.HDC, ctypes.c_void_p]
gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.BitBlt.argtypes = [
    wintypes.HDC,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HDC,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.DWORD,
]
gdi32.GetDIBits.argtypes = [
    wintypes.HDC,
    wintypes.HBITMAP,
    wintypes.UINT,
    wintypes.UINT,
    ctypes.c_void_p,
    ctypes.c_void_p,
    wintypes.UINT,
]
gdi32.GetDIBits.restype = ctypes.c_int


@dataclass
class RawImage:
    """简单的 RGB 位图（每像素 3 字节，行优先，自上而下）。"""

    width: int
    height: int
    data: bytearray

    def copy(self) -> "RawImage":
        return RawImage(self.width, self.height, bytearray(self.data))

    def pixel(self, x: int, y: int) -> tuple[int, int, int]:
        if not (0 <= x < self.width and 0 <= y < self.height):
            return (0, 0, 0)
        offset = (y * self.width + x) * 3
        return (self.data[offset], self.data[offset + 1], self.data[offset + 2])

    def put(self, x: int, y: int, color: tuple[int, int, int]) -> None:
        if not (0 <= x < self.width and 0 <= y < self.height):
            return
        offset = (y * self.width + x) * 3
        self.data[offset : offset + 3] = bytes(
            (max(0, min(255, int(color[0]))), max(0, min(255, int(color[1]))), max(0, min(255, int(color[2]))))
        )

    @classmethod
    def blank(cls, width: int, height: int, color: tuple[int, int, int] = (255, 255, 255)) -> "RawImage":
        width = max(1, int(width))
        height = max(1, int(height))
        row = bytes((color[0], color[1], color[2])) * width
        return cls(width, height, bytearray(row * height))


def virtual_screen() -> tuple[int, int, int, int]:
    """整个虚拟屏幕的 (x, y, 宽, 高)，多显示器时为负坐标起。"""
    try:
        x = int(user32.GetSystemMetrics(SM_XVIRTUALSCREEN))
        y = int(user32.GetSystemMetrics(SM_YVIRTUALSCREEN))
        width = int(user32.GetSystemMetrics(SM_CXVIRTUALSCREEN))
        height = int(user32.GetSystemMetrics(SM_CYVIRTUALSCREEN))
        if width > 0 and height > 0:
            return x, y, width, height
    except Exception:
        pass
    return 0, 0, int(user32.GetSystemMetrics(0) or 1920), int(user32.GetSystemMetrics(1) or 1080)


def grab_screen(x: int, y: int, width: int, height: int) -> RawImage | None:
    """抓取屏幕上一块区域，失败返回 None。"""
    width = int(width)
    height = int(height)
    if width <= 0 or height <= 0:
        return None

    hdc_screen = user32.GetDC(None)
    if not hdc_screen:
        return None
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
    bitmap = gdi32.CreateCompatibleBitmap(hdc_screen, width, height)
    if not hdc_mem or not bitmap:
        if hdc_mem:
            gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(None, hdc_screen)
        return None

    old = gdi32.SelectObject(hdc_mem, bitmap)
    try:
        if not gdi32.BitBlt(hdc_mem, 0, 0, width, height, hdc_screen, int(x), int(y), SRCCOPY):
            return None

        info = BITMAPINFO()
        header = info.bmiHeader
        header.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        header.biWidth = width
        header.biHeight = -height
        header.biPlanes = 1
        header.biBitCount = 32
        header.biCompression = BI_RGB

        buffer = ctypes.create_string_buffer(width * height * 4)
        lines = gdi32.GetDIBits(
            hdc_mem, bitmap, 0, height, buffer, ctypes.byref(info), DIB_RGB_COLORS
        )
        if lines != height:
            return None
        raw = buffer.raw
    finally:
        gdi32.SelectObject(hdc_mem, old)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(None, hdc_screen)

    data = bytearray(width * height * 3)
    data[0::3] = raw[2::4]
    data[1::3] = raw[1::4]
    data[2::3] = raw[0::4]
    return RawImage(width, height, data)


def _chunk(tag: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + tag
        + payload
        + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
    )


def png_bytes(image: RawImage) -> bytes:
    """把 RawImage 编码成 PNG（24 位真彩色）。"""
    stride = image.width * 3
    rows = bytearray()
    source = image.data
    for y in range(image.height):
        rows.append(0)
        start = y * stride
        rows += source[start : start + stride]

    compressor = zlib.compressobj(level=6)
    body = compressor.compress(bytes(rows)) + compressor.flush()
    header = struct.pack(">IIBBBBB", image.width, image.height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", body)
        + _chunk(b"IEND", b"")
    )


def save_png(path, image: RawImage) -> None:
    with open(path, "wb") as handle:
        handle.write(png_bytes(image))


def png_data_uri(image: RawImage) -> str:
    """给 tk.PhotoImage(data=...) 用的 base64 字符串。"""
    import base64

    return base64.b64encode(png_bytes(image)).decode("ascii")


def crop(
    image: RawImage | None, x: int, y: int, width: int, height: int
) -> RawImage | None:
    """从大图里裁一块；越界部分留黑，不抛异常。"""
    if image is None:
        return None
    x = int(x)
    y = int(y)
    width = max(1, int(width))
    height = max(1, int(height))

    data = bytearray(width * height * 3)
    for row in range(height):
        source_y = y + row
        if not (0 <= source_y < image.height):
            continue
        start_x = max(0, x)
        end_x = min(image.width, x + width)
        if end_x <= start_x:
            continue
        source_start = (source_y * image.width + start_x) * 3
        target_start = (row * width + (start_x - x)) * 3
        length = (end_x - start_x) * 3
        data[target_start : target_start + length] = image.data[
            source_start : source_start + length
        ]
    return RawImage(width, height, data)


# ---------------------------------------------------------------- 窗口截图
GA_ROOT = 2
DWMWA_EXTENDED_FRAME_BOUNDS = 9

user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetForegroundWindow.argtypes = []
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.GetCursorPos.restype = wintypes.BOOL
user32.WindowFromPoint.argtypes = [wintypes.POINT]
user32.WindowFromPoint.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL
user32.GetWindowThreadProcessId.argtypes = [
    wintypes.HWND,
    ctypes.POINTER(wintypes.DWORD),
]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD

if dwmapi is not None:
    try:
        dwmapi.DwmGetWindowAttribute.argtypes = [
            wintypes.HWND,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long
    except Exception:
        dwmapi = None


def window_pid(hwnd) -> int:
    pid = wintypes.DWORD()
    try:
        user32.GetWindowThreadProcessId(wintypes.HWND(int(hwnd)), ctypes.byref(pid))
    except Exception:
        return 0
    return int(pid.value)


def window_rect(hwnd) -> tuple[int, int, int, int] | None:
    """窗口在屏幕上的物理像素矩形 (x, y, 宽, 高)。"""
    hwnd = int(hwnd or 0)
    if not hwnd or not user32.IsWindow(hwnd) or user32.IsIconic(hwnd):
        return None

    rect = wintypes.RECT()
    if dwmapi is not None:
        try:
            result = dwmapi.DwmGetWindowAttribute(
                hwnd,
                DWMWA_EXTENDED_FRAME_BOUNDS,
                ctypes.byref(rect),
                ctypes.sizeof(rect),
            )
            if result == 0:
                width = int(rect.right - rect.left)
                height = int(rect.bottom - rect.top)
                if width > 1 and height > 1:
                    return int(rect.left), int(rect.top), width, height
        except Exception:
            pass

    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    width = int(rect.right - rect.left)
    height = int(rect.bottom - rect.top)
    if width <= 1 or height <= 1:
        return None
    return int(rect.left), int(rect.top), width, height


def window_under_cursor() -> int:
    point = wintypes.POINT()
    if not user32.GetCursorPos(ctypes.byref(point)):
        return 0
    hwnd = user32.WindowFromPoint(point)
    if not hwnd:
        return 0
    root = user32.GetAncestor(hwnd, GA_ROOT)
    return int(root or hwnd)


def grab_active_window() -> tuple[RawImage | None, tuple[int, int, int, int] | None]:
    """抓取当前前台窗口；如果前台是本程序，则改用鼠标下的窗口。"""
    own_pid = int(kernel32.GetCurrentProcessId())
    hwnd = int(user32.GetForegroundWindow() or 0)
    if hwnd and window_pid(hwnd) == own_pid:
        hwnd = window_under_cursor()
    if not hwnd or window_pid(hwnd) == own_pid:
        return None, None
    bounds = window_rect(hwnd)
    if bounds is None:
        return None, None
    x, y, width, height = bounds
    return grab_screen(x, y, width, height), bounds


def grab_fullscreen() -> RawImage | None:
    return grab_screen(*virtual_screen())
