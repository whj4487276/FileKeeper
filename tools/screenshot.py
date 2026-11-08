"""开发期截图工具：启动界面、抓取窗口与托盘区域，用于检查排版。

运行：python tools/screenshot.py
产物：docs/screenshots/*.png
"""
from __future__ import annotations

import ctypes
import sys
import tempfile
import time
from ctypes import wintypes
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

try:
    import tkinter as tk
except Exception:  # pragma: no cover
    tk = None

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


user32.GetWindowDC.restype = wintypes.HDC
user32.GetWindowDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
user32.PrintWindow.restype = wintypes.BOOL
user32.FindWindowW.restype = wintypes.HWND
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.ReleaseDC.restype = ctypes.c_int
user32.GetParent.restype = wintypes.HWND
user32.GetParent.argtypes = [wintypes.HWND]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.GetDIBits.argtypes = [
    wintypes.HDC,
    wintypes.HBITMAP,
    wintypes.UINT,
    wintypes.UINT,
    ctypes.c_void_p,
    ctypes.POINTER(BITMAPINFO),
    wintypes.UINT,
]
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
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]
SRCCOPY = 0x00CC0020


def _bits_to_image(mem_dc, bitmap, width: int, height: int) -> Image.Image:
    info = BITMAPINFO()
    info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    info.bmiHeader.biWidth = width
    info.bmiHeader.biHeight = -height
    info.bmiHeader.biPlanes = 1
    info.bmiHeader.biBitCount = 32
    info.bmiHeader.biCompression = 0
    buffer = ctypes.create_string_buffer(width * height * 4)
    gdi32.GetDIBits(mem_dc, bitmap, 0, height, buffer, ctypes.byref(info), 0)
    return Image.frombuffer("RGBA", (width, height), buffer, "raw", "BGRA", 0, 1).convert("RGB")


def capture_window(hwnd, path: Path) -> bool:
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return False
    width = rect.right - rect.left
    height = rect.bottom - rect.top
    if width <= 0 or height <= 0:
        return False

    window_dc = user32.GetWindowDC(hwnd)
    mem_dc = gdi32.CreateCompatibleDC(window_dc)
    bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
    old = gdi32.SelectObject(mem_dc, bitmap)
    user32.PrintWindow(hwnd, mem_dc, 2)
    image = _bits_to_image(mem_dc, bitmap, width, height)
    image.save(path)
    gdi32.SelectObject(mem_dc, old)
    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(mem_dc)
    user32.ReleaseDC(hwnd, window_dc)
    return True


def capture_screen_region(path: Path, x: int, y: int, width: int, height: int) -> bool:
    screen_dc = user32.GetDC(None)
    mem_dc = gdi32.CreateCompatibleDC(screen_dc)
    bitmap = gdi32.CreateCompatibleBitmap(screen_dc, width, height)
    old = gdi32.SelectObject(mem_dc, bitmap)
    gdi32.BitBlt(mem_dc, 0, 0, width, height, screen_dc, x, y, SRCCOPY)
    image = _bits_to_image(mem_dc, bitmap, width, height)
    image.save(path)
    gdi32.SelectObject(mem_dc, old)
    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(mem_dc)
    user32.ReleaseDC(None, screen_dc)
    return True


def seed_config(tmp: Path):
    from fk.config import Config, HistoryEntry, Schedule, Task

    cfg = Config.load(tmp / "config.json")
    # 测试/截图演示统一放在 F:\Backup，避免在其他盘生成测试文件夹
    cfg.settings.backup_root = "F:\\Backup"

    demo = tmp / "下载"
    demo.mkdir(parents=True, exist_ok=True)
    for name, size, days in (
        ("项目备份-20261020.zip", 1_200, 3),
        ("项目备份-20261021.zip", 3_400, 2),
        ("项目备份-20261022.zip", 5_600, 1),
        ("旧资料.rar", 900, 6),
    ):
        file = demo / name
        file.write_bytes(b"x" * size)
        stamp = time.time() - days * 86400
        import os

        os.utime(file, (stamp, stamp))

    def ago(minutes: int) -> str:
        return (datetime.now() - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S")

    cfg.tasks = [
        Task(
            id="t_work",
            name="工作文档",
            sources=["C:\\Users\\WWW\\Documents"],
            target="F:\\Backup\\工作文档",
            mode="mirror",
            schedule=Schedule(type="interval", interval_min=30),
            last_run=ago(12),
            last_status="success",
            last_files=128,
            last_bytes=48_300_000,
        ),
        Task(
            id="t_photo",
            name="照片相册",
            sources=["C:\\Users\\WWW\\Pictures"],
            target="F:\\Backup\\照片相册",
            mode="snapshot",
            keep_versions=5,
            schedule=Schedule(type="daily", time="22:00"),
            last_run=ago(180),
            last_status="success",
            last_files=942,
            last_bytes=1_920_000_000,
        ),
        Task(
            id="t_pick",
            name="最新压缩包",
            sources=[str(demo)],
            target="F:\\Backup\\最新压缩包",
            mode="pick",
            pick_exts=[".zip", ".rar"],
            pick_rule="newest",
            pick_count=2,
            pick_recursive=True,
            schedule=Schedule(type="daily", time="23:30"),
            last_run=ago(60),
            last_status="success",
            last_files=2,
            last_bytes=9_000,
            last_note="挑中：项目备份-20261022.zip、项目备份-20261021.zip",
        ),
    ]

    cfg.history = [
        HistoryEntry(
            id="h1",
            task_id="t_work",
            task_name="工作文档",
            time=ago(12),
            status="success",
            mode="mirror",
            copied=6,
            skipped=122,
            total_bytes=8_400_000,
            duration=3.8,
            dest="F:\\Backup\\工作文档",
        ),
        HistoryEntry(
            id="h2",
            task_id="t_pick",
            task_name="最新压缩包",
            time=ago(60),
            status="success",
            mode="pick",
            copied=2,
            total_bytes=9_000,
            duration=0.6,
            dest="F:\\Backup\\最新压缩包",
            note="挑中：项目备份-20261022.zip、项目备份-20261021.zip",
        ),
        HistoryEntry(
            id="h3",
            task_id="t_photo",
            task_name="照片相册",
            time=ago(180),
            status="success",
            mode="snapshot",
            copied=942,
            total_bytes=1_920_000_000,
            duration=96.4,
            dest="F:\\Backup\\照片相册\\20261023-150200",
            snapshot="20261023-150200",
        ),
        HistoryEntry(
            id="h4",
            task_id="t_work",
            task_name="工作文档",
            time=ago(1500),
            status="failed",
            mode="mirror",
            copied=0,
            total_bytes=0,
            duration=0.3,
            dest="F:\\Backup\\工作文档",
            error="找不到：C:\\Users\\WWW\\Documents",
        ),
    ]
    return cfg, demo


def hwnd_of(tk_window) -> int:
    try:
        hwnd = int(tk_window.winfo_id())
    except Exception:
        return 0
    parent = user32.GetParent(hwnd)
    return int(parent) if parent else hwnd


def main() -> int:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    from fk.ui.app import App

    out_dir = ROOT / "docs" / "screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="fk_shot_"))

    cfg, demo = seed_config(tmp)
    app = App(cfg)
    app.update()
    app.lift()
    app.update()
    time.sleep(1.2)
    app.update()
    main_hwnd = user32.FindWindowW(None, app.title())

    shots = [
        ("tasks", "02-tasks.png"),
        ("settings", "09-settings.png"),
    ]
    ok = 0
    for page, filename in shots:
        app.show_page(page)
        app.update()
        time.sleep(0.9)
        app.update()
        if main_hwnd and capture_window(main_hwnd, out_dir / filename):
            ok += 1
            print(f"captured {filename}")
        else:
            print(f"FAILED {filename} (hwnd={main_hwnd})")

    # 设置页下半部分（托盘 / 自启）
    try:
        from fk.widgets import ScrollFrame

        app.show_page("settings")
        app.update()
        page = app.pages["settings"]
        for child in page.winfo_children():
            if isinstance(child, ScrollFrame):
                child.canvas.yview_moveto(1.0)
        app.update()
        time.sleep(0.8)
        app.update()
        hwnd = main_hwnd
        if hwnd and capture_window(hwnd, out_dir / "11-settings-tray.png"):
            ok += 1
            print("captured 11-settings-tray.png")
    except Exception as exc:  # noqa: BLE001
        print(f"settings scroll capture failed: {exc}")

    # 定时关机页（带演示计划）
    try:
        from datetime import datetime, timedelta

        from fk import shutdown as shutdown_mod

        app.show_page("shutdown")
        app.config.shutdown_plan = shutdown_mod.make_plan(
            datetime.now() + timedelta(hours=16, minutes=35), "tomorrow8"
        )
        app.pages["shutdown"]._refresh_status()
        app.update()
        time.sleep(0.8)
        app.update()
        hwnd = main_hwnd
        if hwnd and capture_window(hwnd, out_dir / "13-shutdown.png"):
            ok += 1
            print("captured 13-shutdown.png")
        app.config.shutdown_plan = None
        app.pages["shutdown"]._refresh_status()
    except Exception as exc:  # noqa: BLE001
        print(f"shutdown page capture failed: {exc}")

    # 时间闹钟页（带演示提醒 + 循环设置）
    try:
        from datetime import datetime, timedelta

        from fk import alarm as alarm_mod

        app.show_page("alarm")
        page = app.pages["alarm"]
        page.repeat_var.set(True)
        page.repeat_mode_var.set("count")
        page.repeat_count_var.set("5")
        page.clock_repeat_var.set("hour_min")
        app.update()

        demo = alarm_mod.make_alarm(
            datetime.now() + timedelta(minutes=12, seconds=30),
            "countdown",
            True,
            True,
            "倒计时 00:12:30",
            "",
            repeat="count",
            repeat_total=5,
            interval_seconds=750,
        )
        demo["fired"] = 1
        app.config.alarm = demo
        page._refresh_status()
        app.update()
        time.sleep(0.8)
        app.update()
        if main_hwnd and capture_window(main_hwnd, out_dir / "14-alarm.png"):
            ok += 1
            print("captured 14-alarm.png")

        # 滚到中间，展示循环 / 间隔提醒控件
        from fk.widgets import ScrollFrame

        for child in page.winfo_children():
            if isinstance(child, ScrollFrame):
                child.canvas.yview_moveto(0.42)
        app.update()
        time.sleep(0.7)
        app.update()
        if main_hwnd and capture_window(main_hwnd, out_dir / "16-alarm-repeat.png"):
            ok += 1
            print("captured 16-alarm-repeat.png")

        app.config.alarm = None
        page.repeat_var.set(False)
        page.clock_repeat_var.set("none")
        page._refresh_status()
    except Exception as exc:  # noqa: BLE001
        print(f"alarm page capture failed: {exc}")

    # 闹钟页下半部分（提醒方式 / 自定义文字）
    try:
        from fk.widgets import ScrollFrame

        app.show_page("alarm")
        app.update()
        page = app.pages["alarm"]
        for child in page.winfo_children():
            if isinstance(child, ScrollFrame):
                child.canvas.yview_moveto(1.0)
        app.update()
        time.sleep(0.7)
        app.update()
        if main_hwnd and capture_window(main_hwnd, out_dir / "15-alarm-message.png"):
            ok += 1
            print("captured 15-alarm-message.png")
    except Exception as exc:  # noqa: BLE001
        print(f"alarm scroll capture failed: {exc}")

    # 计时器页
    try:
        app.show_page("timers")
        page = app.pages["timers"]
        page.timers[0].apply("写文档", "up", 0, 0, "", False)
        page.timers[1].apply("泡面", "down", 300, 0, "可以吃了", True)
        page.timers[2].apply("会议倒计时", "down", 1500, 0, "会议开始", False)
        page.timers[3].apply("健身", "up", 0, 0, "", False)
        page._apply_all()
        page._toggle(page.timers[0])
        page._toggle(page.timers[2])
        time.sleep(1.3)
        page._tick()
        app.update()
        time.sleep(0.5)
        app.update()
        if main_hwnd and capture_window(main_hwnd, out_dir / "17-timers.png"):
            ok += 1
            print("captured 17-timers.png")
        page._reset_all()
    except Exception as exc:  # noqa: BLE001
        print(f"timers page capture failed: {exc}")

    # 计时器结束提醒弹窗
    try:
        from fk.ui.timers import TimerAlertDialog

        box = TimerAlertDialog(app, "泡面", "可以吃了，快来端面～", sound=False)
        box.geometry(f"+{app.winfo_rootx() + sp_px(360)}+{app.winfo_rooty() + sp_px(260)}")
        box.update()
        time.sleep(0.55)
        box.update()
        if capture_window(hwnd_of(box), out_dir / "18-timer-alert.png"):
            ok += 1
            print("captured 18-timer-alert.png")
        box.destroy()
    except Exception as exc:  # noqa: BLE001
        print(f"timer alert capture failed: {exc}")

    # 快速截图页
    try:
        app.show_page("shot")
        app.update()
        # 等快捷键注册完成，截图里的状态才会是“已启用”而不是“正在注册”
        deadline = time.time() + 1.5
        while time.time() < deadline:
            app.update()
            time.sleep(0.03)
        if main_hwnd and capture_window(main_hwnd, out_dir / "19-shot.png"):
            ok += 1
            print("captured 19-shot.png")
    except Exception as exc:  # noqa: BLE001
        print(f"shot page capture failed: {exc}")

    # 截图编辑窗口
    try:
        from fk import annotate as ann_mod
        from fk import capture as cap_mod
        from fk.ui.screenshot import ShotEditor

        ax, ay = app.winfo_rootx(), app.winfo_rooty()
        base = cap_mod.grab_screen(ax + 340, ay + 150, 660, 380)
        if base is not None:
            editor = ShotEditor(app, base)
            editor.geometry(f"+{ax + sp_px(180)}+{ay + sp_px(120)}")
            editor.update()
            red = (255, 59, 48)
            shapes = [
                {"kind": "rect", "x1": 40, "y1": 40, "x2": 300, "y2": 150, "color": red, "width": 4},
                {"kind": "ellipse", "x1": 330, "y1": 40, "x2": 560, "y2": 170, "color": (52, 199, 89), "width": 4},
                {"kind": "arrow", "x1": 330, "y1": 300, "x2": 520, "y2": 120, "color": (47, 123, 255), "width": 4},
            ]
            for shape in shapes:
                editor.shapes.append(shape)
                ann_mod.apply_shape(editor.display_image, shape)
            editor._refresh_image()
            editor._set_color(red)
            editor.update()
            time.sleep(0.55)
            editor.update()
            if capture_window(hwnd_of(editor), out_dir / "20-shot-editor.png"):
                ok += 1
                print("captured 20-shot-editor.png")
            editor.destroy()
    except Exception as exc:  # noqa: BLE001
        print(f"shot editor capture failed: {exc}")

    # 退出确认（有未执行的关机计划时）
    try:
        from datetime import datetime, timedelta

        import fk.ui.shutdown as shutdown_ui

        from fk import shutdown as sdm

        app.config.shutdown_plan = sdm.make_plan(
            datetime.now() + timedelta(hours=3, minutes=25), "hours10"
        )
        dialog = shutdown_ui.ExitShutdownDialog(app, app.config.shutdown_plan)
        dialog.geometry(
            f"+{app.winfo_rootx() + sp_px(430)}+{app.winfo_rooty() + sp_px(280)}"
        )
        dialog.update()
        time.sleep(0.5)
        dialog.update()
        if capture_window(hwnd_of(dialog), out_dir / "21-exit-shutdown.png"):
            ok += 1
            print("captured 21-exit-shutdown.png")
        dialog._choose("abort")
        app.config.shutdown_plan = None
        app.pages["shutdown"]._refresh_status()
    except Exception as exc:  # noqa: BLE001
        print(f"exit dialog capture failed: {exc}")

    # 托盘区域
    screen_w = user32.GetSystemMetrics(0)
    screen_h = user32.GetSystemMetrics(1)
    width, height = 640, 80
    if capture_screen_region(
        out_dir / "06-tray-area.png", screen_w - width, screen_h - height, width, height
    ):
        ok += 1
        print("captured 06-tray-area.png")

    # 托盘右键菜单（合成：应用窗口 + 菜单 + 二级菜单）
    try:
        app.show_page("tasks")
        app.update()
        app._show_tray_menu()
        app.update()
        time.sleep(0.5)
        app.update()
        menu = app._tray_menu

        def walk(widget):
            for child in widget.winfo_children():
                yield child
                yield from walk(child)

        parent_row = None
        if menu is not None:
            for widget in walk(menu):
                if isinstance(widget, tk.Label) and "定时关机" in str(widget.cget("text")):
                    parent_row = widget
                    break
        if parent_row is not None:
            app._open_submenu(
                parent_row,
                [
                    ("明天 08:00 关机", lambda: None),
                    ("今天 08:00 关机", lambda: None),
                    ("10 小时后关机", lambda: None),
                    None,
                    ("自定义关机…", lambda: None),
                ],
            )
        app.update()
        time.sleep(0.5)
        app.update()

        app_hwnd = main_hwnd
        base_path = out_dir / "_base.png"
        if capture_window(app_hwnd, base_path):
            base = Image.open(base_path).convert("RGB")
            ax, ay = app.winfo_rootx(), app.winfo_rooty()
            for panel, name in ((app._tray_menu, "_menu.png"), (app._submenu, "_sub.png")):
                if panel is None:
                    continue
                shot = out_dir / name
                if not capture_window(hwnd_of(panel), shot):
                    continue
                image = Image.open(shot).convert("RGB")
                px = panel.winfo_rootx() - ax
                py = panel.winfo_rooty() - ay
                base.paste(image, (max(0, px), max(0, py)))
            base.save(out_dir / "07-tray-menu.png")
            ok += 1
            print("captured 07-tray-menu.png")
            for temp in ("_base.png", "_menu.png", "_sub.png"):
                (out_dir / temp).unlink(missing_ok=True)
        app._close_tray_menu()
    except Exception as exc:  # noqa: BLE001
        print(f"tray menu capture failed: {exc}")

    # 任务对话框：镜像 / 智能挑选
    try:
        from fk.ui.tasks import TaskDialog

        dialog = TaskDialog(app, cfg.tasks[0], lambda _t, _n: None)
        dialog.geometry(f"+{sp_px(120)}+{sp_px(20)}")
        dialog.update()
        dialog.lift()
        dialog.update()
        time.sleep(1.0)
        dialog.update()
        if capture_window(hwnd_of(dialog), out_dir / "04-dialog.png"):
            ok += 1
            print("captured 04-dialog.png")
        dialog.destroy()
    except Exception as exc:  # noqa: BLE001
        print(f"dialog capture failed: {exc}")

    try:
        from fk.ui.tasks import TaskDialog

        dialog = TaskDialog(app, cfg.tasks[2], lambda _t, _n: None)
        dialog.update()
        dialog.lift()
        dialog.update()
        time.sleep(0.8)
        dialog.update()
        if capture_window(hwnd_of(dialog), out_dir / "08-dialog-pick.png"):
            ok += 1
            print("captured 08-dialog-pick.png")

        from fk.widgets import ScrollFrame

        for frame in ScrollFrame._registry:
            try:
                if frame.winfo_toplevel() is dialog:
                    frame.canvas.yview_moveto(1.0)
                    break
            except Exception:
                continue
        dialog.update()
        time.sleep(0.6)
        dialog.update()
        if capture_window(hwnd_of(dialog), out_dir / "10-dialog-schedule.png"):
            ok += 1
            print("captured 10-dialog-schedule.png")
        dialog.destroy()
    except Exception as exc:  # noqa: BLE001
        print(f"pick dialog capture failed: {exc}")

    app.quit_app()
    print(f"done, {ok} screenshots")
    return 0


def sp_px(value: int) -> int:
    from fk.theme import sp

    return sp(value)


if __name__ == "__main__":
    sys.exit(main())
