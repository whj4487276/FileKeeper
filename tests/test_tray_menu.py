"""托盘右键菜单逐项有效性自测。

运行：python tests\\test_tray_menu.py
不执行真实关机、截图、打开目录或退出。
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fk.config import Config  # noqa: E402
from fk.ui.app import App  # noqa: E402

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


def label_tree(parent):
    result = []
    for widget in parent.winfo_children():
        try:
            result.append((widget.cget("text"), widget))
        except Exception:
            result.extend(label_tree(widget))
    return result


def click_label(widget) -> None:
    # 真实鼠标点击子菜单会让子 Toplevel 获得焦点；这里模拟同样的焦点变化。
    try:
        widget.focus_set()
    except Exception:
        pass
    widget.event_generate("<Button-1>")


def main() -> int:
    print("=" * 60)
    print("电脑百宝箱 · 托盘右键菜单自测")
    print("=" * 60)
    base = Path(tempfile.mkdtemp(prefix="fk_tray_menu_test_"))
    cfg = Config.load(base / "config.json")
    cfg.settings.backup_root = str(base / "backup")
    app = App(cfg)
    app.update()
    app.withdraw()
    app.update()

    called: list[tuple[str, object]] = []
    original_open_shutdown = app._open_shutdown_page
    original_open_shot = app._open_shot_settings
    app._quick_shutdown = lambda source: called.append(("shutdown", source))
    app._quick_alarm = lambda minutes: called.append(("alarm", minutes))
    app._tray_capture = lambda action_id: called.append(("capture", action_id))
    app._open_shutdown_page = lambda: called.append(("shutdown_page", None))
    app._open_alarm_page = lambda: called.append(("alarm_page", None))
    app._open_shot_settings = lambda: called.append(("shot_settings", None))
    app._tray_open_root = lambda: called.append(("open_root", None))
    app.quit_app = lambda: called.append(("quit", None))

    def open_menu():
        if app._tray_menu is not None:
            app._close_tray_menu()
        app._show_tray_menu()
        app.update()

    def click_submenu(parent_prefix: str, child_prefix: str) -> None:
        open_menu()
        rows = label_tree(app._tray_menu)
        parent = next(w for text, w in rows if text.startswith(parent_prefix))
        parent.event_generate("<Enter>")
        app.update()
        panel = app._submenu
        check(panel is not None, f"「{parent_prefix}」子菜单已展开")
        if panel is None:
            return
        children = label_tree(panel)
        child = next(w for text, w in children if text.startswith(child_prefix))
        click_label(child)
        app.update()

    def click_top(text: str) -> None:
        open_menu()
        row = next(w for label, w in label_tree(app._tray_menu) if label == text)
        click_label(row)
        app.update()

    # 定时关机
    for prefix, source in (
        ("明天 08:00 关机", "tomorrow8"),
        ("今天 08:00 关机", "today8"),
        ("10 小时后关机", "hours10"),
    ):
        called.clear()
        click_submenu("定时关机", prefix)
        check(called == [("shutdown", source)], f"定时关机 → {prefix}")
        check(app._tray_menu is None, f"点击「{prefix}」后菜单关闭")
    called.clear()
    click_submenu("定时关机", "自定义关机")
    check(called == [("shutdown_page", None)], "定时关机 → 自定义关机…")
    check(app._tray_menu is None, "点击「自定义关机…」后菜单关闭")

    # 时间闹钟
    for prefix, minutes in (("15 分钟后提醒", 15), ("60 分钟后提醒", 60)):
        called.clear()
        click_submenu("时间闹钟", prefix)
        check(called == [("alarm", minutes)], f"时间闹钟 → {prefix}")
    called.clear()
    click_submenu("时间闹钟", "自定义提醒")
    check(called == [("alarm_page", None)], "时间闹钟 → 自定义提醒…")

    # 截图
    for prefix, action in (
        ("区域截图", "capture.region"),
        ("全屏截图", "capture.fullscreen"),
        ("窗口截图", "capture.window"),
    ):
        called.clear()
        click_submenu("截图", prefix)
        check(called == [("capture", action)], f"截图 → {prefix}")
    called.clear()
    click_submenu("截图", "快捷键设置")
    check(called == [("shot_settings", None)], "截图 → 快捷键设置…")

    # 顶层项
    called.clear()
    click_top("打开备份目录")
    check(called == [("open_root", None)], "打开备份目录")
    check(app._tray_menu is None, "打开备份目录后菜单关闭")
    called.clear()
    click_top("退出电脑百宝箱")
    check(called == [("quit", None)], "退出电脑百宝箱")
    check(app._tray_menu is None, "退出后菜单关闭")

    # 真实命令：自定义关机 / 快捷键设置应把主窗口叫出来并切页
    app._open_shot_settings = original_open_shot
    app._open_shutdown_page = original_open_shutdown
    app.hide_window()
    app.update()
    app._open_shot_settings()
    app.update()
    check(not app._hidden and app.current_page == "shot", "自定义快捷键设置会显示并切到截图页")
    app.hide_window()
    app.update()
    app._open_shutdown_page()
    app.update()
    check(not app._hidden and app.current_page == "shutdown", "自定关机入口会显示并切到关机页")

    app._closed = True
    if app.tray is not None:
        app.tray.stop()
    app.destroy()
    print("\n" + "=" * 60)
    print(f"通过 {PASSED} 项，失败 {FAILED} 项")
    print("=" * 60)
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
