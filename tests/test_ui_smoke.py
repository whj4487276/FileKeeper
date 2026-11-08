"""界面冒烟测试：构建所有页面、打开任务对话框、跑一次真实的备份流程。

运行：python tests\test_ui_smoke.py
窗口不会显示（启动后立即隐藏）。
"""
from __future__ import annotations

import sys
import tempfile
import time
import tkinter as tk
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fk.config import Config, Schedule, Task  # noqa: E402

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


def main() -> int:
    from fk.ui.app import App

    tmp = Path(tempfile.mkdtemp(prefix="fk_ui_"))
    cfg = Config.load(tmp / "config.json")
    cfg.settings.backup_root = str(tmp / "backup")

    src = tmp / "src"
    (src / "docs").mkdir(parents=True)
    (src / "readme.txt").write_text("hello", encoding="utf-8")
    (src / "docs" / "note.md").write_text("# note", encoding="utf-8")

    print("=" * 60)
    print("电脑百宝箱 · 界面冒烟测试")
    print("=" * 60)

    app = App(cfg)
    app.withdraw()
    check(True, "主窗口创建成功")
    check(app.tray is not None, "系统托盘图标创建成功")

    check(len(app.pages) == 6, f"页面数量为 6（实际 {len(app.pages)}）")
    for key in ("shutdown", "alarm", "timers", "shot", "tasks", "settings"):
        try:
            app.show_page(key)
            app.update_idletasks()
            check(True, f"页面切换正常：{key}")
        except Exception as exc:  # noqa: BLE001
            check(False, f"页面切换失败：{key} -> {exc}")
    check("home" not in app.pages, "概览页已并入备份任务")
    check("history" not in app.pages, "备份历史页已删除")
    check("files" not in app.pages, "文件管理页已删除")
    check(
        list(app.nav_buttons)
        == ["shutdown", "alarm", "timers", "shot", "tasks", "settings"],
        f"导航顺序正确：{list(app.nav_buttons)}",
    )

    # 计时器页
    try:
        import time as _time

        from fk import timers as timers_mod

        app.show_page("timers")
        page = app.pages["timers"]
        check(len(page.timers) == timers_mod.MAX_TIMERS, "10 个计时器")
        check(len(page._cells) == timers_mod.MAX_TIMERS, "面板 10 个格子")
        check(len(page._set_buttons) == timers_mod.MAX_TIMERS, "面板下方 10 个设置按钮")

        # 2 行 5 列：1-5 在第一行，6-10 在第二行
        positions = [
            (int(page._cells[i]["index"].master.grid_info()["row"]),
             int(page._cells[i]["index"].master.grid_info()["column"]))
            for i in range(10)
        ]
        check(positions[:5] == [(0, 0), (0, 1), (0, 2), (0, 3), (0, 4)], f"第一行 1-5：{positions[:5]}")
        check(positions[5:] == [(1, 0), (1, 1), (1, 2), (1, 3), (1, 4)], f"第二行 6-10：{positions[5:]}")

        cell_labels = [
            str(w.cget("text"))
            for w in page._cells[0]["index"].master.winfo_children()
            if isinstance(w, tk.Label)
        ]
        check("1" in cell_labels, "格子里有序号")
        check(
            page.timers[0].title not in cell_labels,
            f"面板不显示标题（{page.timers[0].title}）",
        )
        check(
            page._cells[0]["clock"].cget("text") == "00:00:00", "未开始显示 00:00:00"
        )
        check(
            str(page._cells[0]["clock"].cget("fg")).upper() == "#FFFFFF", "未工作为白色文字"
        )
        check(
            str(page._cells[0]["index"].master.cget("bg")).upper() == "#000000",
            "面板为黑色背景",
        )

        page._toggle(page.timers[0])
        _time.sleep(1.1)
        page._tick()
        app.update_idletasks()
        text = str(page._cells[0]["clock"].cget("text"))
        check(text.startswith("00:00:0") and text != "00:00:00", f"开始后开始计时（{text}）")
        check(
            str(page._cells[0]["clock"].cget("fg")).upper() == "#3ECF8E", "工作中为绿色文字"
        )
        check(page._cells[0]["button"].cget("text") == "停止", "按钮变为「停止」")
        check(
            str(page._cells[1]["clock"].cget("text")) == "00:00:00", "其他计时器不受影响"
        )

        page._toggle(page.timers[0])
        check(page.timers[0].status == timers_mod.STATUS_IDLE, "再次点击停止")
        check(
            str(page._cells[0]["clock"].cget("text")) == "00:00:00"
            and str(page._cells[0]["clock"].cget("fg")).upper() == "#FFFFFF",
            "停止后归零并回到白色",
        )
        check(page._cells[0]["button"].cget("text") == "开始", "按钮回到「开始」")

        # 倒计时未开始显示设定时长
        page.timers[1].apply("泡面", "down", 180, 0, "可以吃了")
        page._apply_row(page.timers[1])
        check(
            str(page._cells[1]["clock"].cget("text")) == "00:03:00",
            "倒计时未开始显示设定时长",
        )
        check(
            str(page._cells[1]["clock"].cget("fg")).upper() == "#FF3B30",
            "倒计时用红色文字",
        )
        check(
            str(page._set_buttons[1].cget("text")) == "泡面", "设置按钮用标题做名字"
        )

        # 单击序号：在序号与标题之间切换
        check(str(page._cells[0]["index"].cget("text")) == "1", "默认显示序号")
        page._toggle_label(page.timers[0])
        check(
            str(page._cells[0]["index"].cget("text")) == page.timers[0].title,
            "单击后显示标题",
        )
        page._toggle_label(page.timers[0])
        check(str(page._cells[0]["index"].cget("text")) == "1", "再点切回序号")

        # 倒计时到点：弹窗 + 回到初始数字
        import fk.ui.timers as timers_ui

        seen = []
        original_alert = timers_ui.TimerAlertDialog
        timers_ui.TimerAlertDialog = lambda *a, **k: seen.append(
            (a[1], a[2], k.get("sound"))
        )
        try:
            for item in page.timers:
                item.stop()
            timer = page.timers[2]
            timer.apply("会议", "down", 3, 0, "会议开始", True)
            page._apply_row(timer)
            timer.start(now=0.0)
            page._tick()
            app.update_idletasks()
            check(len(seen) == 1, f"到点弹出提醒（{len(seen)} 次）")
            check(bool(seen) and seen[0][0] == "会议", "弹窗大标题用计时器名称")
            check(bool(seen) and seen[0][1] == "会议开始", "弹窗内容用自定义文字")
            check(bool(seen) and seen[0][2] is True, "声音报警开关传到弹窗")
            check(
                str(page._cells[2]["clock"].cget("text")) == "00:00:03",
                "到点后显示设定的初始数字",
            )
        finally:
            timers_ui.TimerAlertDialog = original_alert

        # 提醒弹窗外观与闪烁
        try:
            box = timers_ui.TimerAlertDialog(app, "泡面", "可以吃了", sound=False)
            box.withdraw()
            box.update_idletasks()
            check(str(box.head.cget("fg")).upper() == "#FF2D2D", "标题为红色大字")
            box._flash(True)
            check(str(box.head.cget("bg")).upper() == "#FFD400", "背景可切到黄色")
            box._flash(False)
            check(str(box.head.cget("bg")).upper() == "#000000", "背景可切回黑色")
            box.destroy()
            check(True, "提醒弹窗可正常关闭")
        except Exception as exc:  # noqa: BLE001
            check(False, f"提醒弹窗异常：{exc}")

        # 设置对话框
        dialog = timers_mod.Timer(3)
        try:
            from fk.ui.timers import TimerDialog

            box = TimerDialog(app, dialog, lambda *a: None)
            box.withdraw()
            box.update_idletasks()
            box.destroy()
            check(True, "计时器设置对话框可构建")
        except Exception as exc:  # noqa: BLE001
            check(False, f"计时器设置对话框异常：{exc}")
    except Exception as exc:  # noqa: BLE001
        check(False, f"计时器页异常：{exc}")

    # 快速截图：选区 → 确认 → 编辑 → 保存
    try:
        from fk import annotate as ann_mod
        from fk import capture as cap_mod
        from fk.ui.screenshot import CaptureOverlay, ShotEditor

        app.show_page("shot")
        page = app.pages["shot"]
        check(
            "Ctrl+Alt+A" in str(page._rows["capture.region"]["binding"].cget("text")),
            "显示区域截图快捷键",
        )

        # 用假后端验证多热键 UI：注册失败标红、内部冲突、禁用、替换
        from fk import hotkey as hk_mod
        from fk.hotkeys import (
            STATUS_ACTIVE,
            STATUS_DISABLED,
            HotkeyRegistry,
            RegisterResult,
        )
        from fk.ui.app import TrayHotkeyBackend

        class FakeBackend:
            def __init__(self):
                self.active = {}
                self.fail = set()
                self.next_id = 1

            def register(self, modifiers, vk):
                key = (modifiers & hk_mod.ALL_MODIFIERS, vk)
                if key in self.fail:
                    return RegisterResult(False, 0, 1409)
                hotkey_id = self.next_id
                self.next_id += 1
                self.active[hotkey_id] = key
                return RegisterResult(True, hotkey_id, 0)

            def unregister(self, hotkey_id):
                self.active.pop(hotkey_id, None)
                return True, 0

        original_registry = app.hotkey_registry
        if original_registry is not None:
            original_registry.stop()
        backend = FakeBackend()
        registry = HotkeyRegistry(
            backend,
            config=None,
            on_change=app._on_hotkeys_changed,
        )
        app.hotkey_registry = registry
        registry.start()
        app._refresh_hotkey_ui()
        check(
            registry.state("capture.region").status == STATUS_ACTIVE,
            "区域截图热键已注册",
        )
        check(
            str(page._rows["capture.region"]["status"].cget("text")) == "已注册",
            "界面显示已注册",
        )

        # 外部冲突：旧绑定保留，状态标红
        backend.fail.add((hk_mod.MOD_CONTROL | hk_mod.MOD_ALT, ord("D")))
        result = app.apply_hotkey(
            "capture.region", hk_mod.MOD_CONTROL | hk_mod.MOD_ALT, ord("D")
        )
        check(not result.ok and result.external, "外部冲突被识别")
        check(
            registry.binding("capture.region").text == "Ctrl+Alt+A",
            "外部冲突不覆盖原绑定",
        )
        check(
            registry.state("capture.region").status == STATUS_ACTIVE
            and bool(registry.state("capture.region").error),
            "外部冲突时旧键仍注册并带错误提示",
        )
        check(
            "仍用旧键"
            in str(page._rows["capture.region"]["status"].cget("text")),
            "界面提示仍在使用旧键",
        )

        # 内部冲突
        result = app.apply_hotkey(
            "capture.fullscreen",
            hk_mod.MOD_CONTROL | hk_mod.MOD_ALT,
            ord("A"),
        )
        check(
            not result.ok
            and result.conflict_action == "capture.region",
            "内部冲突指向区域截图",
        )

        # 替换后对方解除绑定
        result = app.apply_hotkey(
            "capture.fullscreen",
            hk_mod.MOD_CONTROL | hk_mod.MOD_ALT,
            ord("A"),
            replace=True,
        )
        check(result.ok, "确认替换后全屏截图绑定成功")
        check(
            registry.state("capture.region").status == STATUS_DISABLED,
            "被替换的区域截图已禁用",
        )

        # 禁用 / 启用
        result = app.set_hotkey_enabled("capture.fullscreen", False)
        check(result.ok, "可禁用全屏截图")
        check(
            registry.state("capture.fullscreen").status == STATUS_DISABLED,
            "禁用状态正确",
        )
        check(
            app.config.capture_hotkeys["items"][0]["action"]
            == "capture.region",
            "配置包含新的多热键结构",
        )

        # 恢复真实注册表
        registry.stop()
        from fk.hotkeys import normalize_config

        app.config.set_capture_hotkeys(normalize_config(None)[0])
        app.hotkey_registry = HotkeyRegistry(
            TrayHotkeyBackend(app.tray),
            config=app.config.capture_hotkeys,
            on_change=app._on_hotkeys_changed,
        )
        app.hotkey_registry.start()
        app._refresh_hotkey_ui()

        # 录制态：Esc 取消、Backspace/Delete 清空、修饰键可后按
        from fk.ui.screenshot import HotkeyDialog

        class FakeKey:
            def __init__(self, keysym, state=0):
                self.keysym = keysym
                self.state = state

        recorded = []
        recorder = HotkeyDialog(
            app,
            "区域截图",
            0,
            0,
            lambda modifiers, vk: (
                recorded.append((modifiers, vk)) or (True, "")
            ),
        )
        recorder.withdraw()
        recorder._on_key(FakeKey("a"))
        recorder._on_key(FakeKey("Control_L"))
        check(
            recorder._mods == hk_mod.MOD_CONTROL and recorder._vk == ord("A"),
            "修饰键后按也能组成 Ctrl+A",
        )
        recorder._on_key(FakeKey("BackSpace"))
        check(recorder._vk == 0, "Backspace 清空录制结果")
        recorder._on_key(FakeKey("Control_L"))
        recorder._on_key(FakeKey("a", 0x0004))
        recorder._save()
        check(recorded and recorded[-1][1] == ord("A"), "保存录制结果")

        class FakeEvent:
            def __init__(self, x, y):
                self.x = x
                self.y = y

        captured = []
        overlay = CaptureOverlay(
            app,
            on_done=lambda image: captured.append(image),
            on_cancel=lambda message: captured.append(message),
        )
        overlay.update()
        overlay._press(FakeEvent(40, 40))
        overlay._drag(FakeEvent(180, 130))
        overlay._release(FakeEvent(180, 130))
        check(overlay._selection is not None, "拖拽后形成选区")
        selection = overlay._selection
        if selection:
            check(
                selection[2] - selection[0] >= 130 and selection[3] - selection[1] >= 80,
                f"选区尺寸合理（{selection[2] - selection[0]}×{selection[3] - selection[1]}）",
            )
        overlay._confirm()
        app.update()
        check(len(captured) == 1, f"双击确认后回调一次（{len(captured)}）")
        image = captured[0] if captured else None
        check(
            image is not None and getattr(image, "width", 0) > 0,
            "截到有效图片",
        )

        if image is not None and hasattr(image, "width"):
            editor = ShotEditor(app, image)
            editor.withdraw()
            editor.update_idletasks()
            check(editor.photo.width() == image.width, "编辑窗口载入截图")
            check(editor.tool == "rect", "默认工具是矩形")

            editor.tool_var.set("ellipse")
            editor.update_idletasks()
            check(editor.tool == "ellipse", "可切换到椭圆工具")
            editor.tool_var.set("arrow")
            editor.update_idletasks()
            check(editor.tool == "arrow", "可切换到箭头工具")

            editor._set_color((255, 212, 0))
            check(editor.color == (255, 212, 0), "可选择颜色")
            editor.width_var.set("6")
            check(editor.line_width == 6, "可调整粗细")

            editor.shapes.append(
                {
                    "kind": "rect",
                    "x1": 5,
                    "y1": 5,
                    "x2": 60,
                    "y2": 40,
                    "color": editor.color,
                    "width": editor.line_width,
                }
            )
            editor._paint(5, 5, 60, 40, shape=editor.shapes[-1])
            check(len(editor.canvas.find_all()) >= 2, "画布上有标注图形")

            from tkinter import filedialog as fd

            out_path = Path(tmp) / "shot_test.png"
            original = fd.asksaveasfilename
            fd.asksaveasfilename = lambda **_k: str(out_path)
            try:
                editor.save()
            finally:
                fd.asksaveasfilename = original
            check(out_path.exists() and out_path.stat().st_size > 50, "保存截图文件成功")
            check(
                app.config.screenshot_prefs.get("last_dir") == str(Path(tmp)),
                "记住上次保存目录",
            )
            saved_bytes = out_path.read_bytes()
            check(saved_bytes[:8] == b"\x89PNG\r\n\x1a\n", "保存的是 PNG")
            width, height = (
                int.from_bytes(saved_bytes[16:20], "big"),
                int.from_bytes(saved_bytes[20:24], "big"),
            )
            check((width, height) == (image.width, image.height), "保存尺寸与原图一致")

            rendered = ann_mod.render(image, editor.shapes)
            check(rendered.width == image.width, "render 结果可用")

            # 默认名称按当前时间生成；上次目录失效时回退到系统图片目录
            from fk.paths import pictures_dir
            from fk.saveutils import default_screenshot_name

            captured = {}

            def fake_cancel(**kwargs):
                captured.update(kwargs)
                return ""

            app.config.set_screenshot_prefs(last_dir=str(Path(tmp) / "missing-dir"))
            fd.asksaveasfilename = fake_cancel
            try:
                editor.save()
            finally:
                fd.asksaveasfilename = original
            check(
                captured.get("initialfile") == default_screenshot_name() + ".png",
                f"默认文件名为百宝箱+日期+时间（{captured.get('initialfile')}）",
            )
            check(
                Path(str(captured.get("initialdir"))) == pictures_dir(),
                "失效目录回退到系统图片目录",
            )
            check(not editor._saving, "取消保存后释放保存状态")
            app.config.set_screenshot_prefs(last_dir=str(Path(tmp)))

            # 只读目标：提示后重新选择，最终保存到新文件
            import os
            import stat
            from tkinter import messagebox as mb

            readonly = Path(tmp) / "readonly_target.png"
            readonly.write_bytes(b"old")
            os.chmod(readonly, stat.S_IREAD)
            good = Path(tmp) / "after_retry.png"
            sequence = [str(readonly), str(good)]
            calls = []

            def fake_sequence(**kwargs):
                calls.append(kwargs.get("initialfile"))
                return sequence.pop(0) if sequence else ""

            original_error = mb.showerror
            mb.showerror = lambda *a, **k: None
            fd.asksaveasfilename = fake_sequence
            try:
                editor.save()
            finally:
                fd.asksaveasfilename = original
                mb.showerror = original_error
                os.chmod(readonly, stat.S_IWRITE)
            check(
                len(calls) >= 2 and good.exists(),
                "只读目标会提示并重新选择目录/文件名",
            )
            check(
                not list(Path(tmp).glob(".fk_shot_*")),
                "重试保存后没有临时文件",
            )
            app.config.set_screenshot_prefs(last_dir=str(Path(tmp)))

            # 网络路径：实际写入走后台线程，完成后恢复保存状态
            from fk.ui import screenshot as screenshot_mod

            network_target = Path(tmp) / "network_like.png"
            original_network = screenshot_mod.is_network_path
            screenshot_mod.is_network_path = lambda _path: True
            fd.asksaveasfilename = lambda **_k: str(network_target)
            try:
                editor.save()
                end = time.time() + 3.0
                while time.time() < end and editor._saving:
                    app.update()
                    time.sleep(0.02)
            finally:
                screenshot_mod.is_network_path = original_network
                fd.asksaveasfilename = original
            check(
                network_target.exists() and not editor._saving,
                "网络路径保存走后台线程并能完成",
            )
            check(
                not list(Path(tmp).glob(".fk_shot_*")),
                "网络保存后没有临时文件",
            )
            app.config.set_screenshot_prefs(last_dir=str(Path(tmp)))

            editor.destroy()

        # 主窗口藏在托盘时，编辑窗口必须能独立显示（不能跟着一起被隐藏）
        try:
            app.hide_window()
            app.update()
            hidden_editor = ShotEditor(
                app, cap_mod.RawImage.blank(120, 80, (240, 240, 240))
            )
            hidden_editor.update()
            check(bool(hidden_editor.winfo_ismapped()), "托盘隐藏时编辑窗口能独立显示")
            check(not app.is_visible(), "编辑窗口打开时主界面保持隐藏")
            hidden_editor.destroy()
        finally:
            app.show_window()
            app.update()
        # 全屏 / 窗口截图：防重入、打开编辑窗口
        try:
            original_full = cap_mod.grab_fullscreen
            original_window = cap_mod.grab_active_window
            cap_mod.grab_fullscreen = lambda: cap_mod.RawImage.blank(
                64, 48, (30, 60, 90)
            )
            cap_mod.grab_active_window = lambda: (
                cap_mod.RawImage.blank(50, 40, (90, 60, 30)),
                (0, 0, 50, 40),
            )
            page.start_action("capture.fullscreen")
            check(page._capturing, "截图进行中会置防重入标记")
            page.start_action("capture.fullscreen")
            end = time.time() + 0.8
            while time.time() < end:
                app.update()
                time.sleep(0.02)
            check(not page._capturing, "全屏截图完成后释放防重入标记")
            editors = [
                widget
                for widget in app.winfo_children()
                if isinstance(widget, ShotEditor)
            ]
            check(bool(editors), "全屏截图打开编辑窗口")
            for widget in editors:
                widget.destroy()

            page.start_action("capture.window")
            end = time.time() + 0.8
            while time.time() < end:
                app.update()
                time.sleep(0.02)
            editors = [
                widget
                for widget in app.winfo_children()
                if isinstance(widget, ShotEditor)
            ]
            check(bool(editors), "窗口截图打开编辑窗口")
            for widget in editors:
                widget.destroy()
        except Exception as exc:  # noqa: BLE001
            check(False, f"全屏/窗口截图异常：{exc}")
        finally:
            cap_mod.grab_fullscreen = original_full
            cap_mod.grab_active_window = original_window
    except Exception as exc:  # noqa: BLE001
        check(False, f"快速截图异常：{exc}")

    # 定时关机页（只模拟状态，不真的调用 shutdown）
    try:
        from datetime import datetime, timedelta

        from fk import shutdown as shutdown_mod

        page = app.pages["shutdown"]
        app.config.shutdown_plan = shutdown_mod.make_plan(
            datetime.now() + timedelta(hours=2), "custom_delay"
        )
        page._refresh_status()
        app.update_idletasks()
        text = page.status_text.cget("text")
        check("将在" in str(text), f"关机状态显示正常（{text}）")
        check(page.cancel_btn._enabled, "取消关机按钮已启用")
        app.config.shutdown_plan = None
        page._refresh_status()
        check("未设置" in str(page.status_text.cget("text")), "清除后恢复未设置状态")
    except Exception as exc:  # noqa: BLE001
        check(False, f"定时关机页异常：{exc}")

    # 时间闹钟页
    try:
        from datetime import datetime, timedelta

        from fk import alarm as alarm_mod

        app.show_page("alarm")
        page = app.pages["alarm"]
        target = datetime.now() + timedelta(minutes=5)
        app.config.alarm = alarm_mod.make_alarm(target, "countdown", True, True, "测试提醒")
        page._refresh_status()
        app.update_idletasks()
        check("提醒" in str(page.status_text.cget("text")), "闹钟状态显示正常")
        check("剩余" in str(page.countdown.cget("text")), "倒计时文本正常")

        # 模拟到点：关闭声音与弹窗，验证触发链路（不会真的响铃/弹窗）
        app.config.alarm = alarm_mod.make_alarm(
            datetime.now() - timedelta(seconds=1), "countdown", False, False, "已到点"
        )
        page._tick()
        check(app.config.alarm is None, "到点后计划被清除")
        check("没有正在进行" in str(page.status_text.cget("text")), "到点后状态复位")

        # 自定义提醒文字
        page.text_var.set("该喝水了")
        page.sound_var.set(False)
        page.dialog_var.set(True)
        page._set_alarm(datetime.now() + timedelta(minutes=3), "countdown", "测试", confirm=False)
        check(
            (app.config.alarm or {}).get("text") == "该喝水了",
            f"自定义文字已保存（{(app.config.alarm or {}).get('text')}）",
        )
        check(
            app.config.alarm_prefs.get("text") == "该喝水了", "提醒文字已记住，供下次使用"
        )

        # 托盘快捷：15 分钟
        app._quick_alarm(15)
        target2 = alarm_mod.alarm_target(app.config.alarm)
        remaining = int((target2 - datetime.now()).total_seconds())
        check(880 <= remaining <= 900, f"托盘「15 分钟」设定正确（{remaining} 秒）")
        app.cancel_alarm()

        # 提醒弹窗可构建（含自定义文字）
        try:
            from fk.ui.alarm import ReminderDialog

            dialog = ReminderDialog(app, "该喝水了", "倒计时 15 分钟 · 2026-10-24 17:30:00")
            dialog.withdraw()
            dialog.update_idletasks()
            dialog.destroy()
            check(True, "提醒弹窗可构建")
        except Exception as exc:  # noqa: BLE001
            check(False, f"提醒弹窗异常：{exc}")
    except Exception as exc:  # noqa: BLE001
        check(False, f"时间闹钟页异常：{exc}")

    # 托盘菜单与二级菜单
    try:
        app._show_tray_menu()
        app.update_idletasks()
        check(app._tray_menu is not None, "托盘菜单可展开")

        def walk(widget):
            for child in widget.winfo_children():
                yield child
                yield from walk(child)

        parent_row = None
        for widget in walk(app._tray_menu):
            if isinstance(widget, tk.Label) and "定时关机" in str(widget.cget("text")):
                parent_row = widget
                break
        check(parent_row is not None, "找到「定时关机」父菜单项")
        check(
            any(
                isinstance(widget, tk.Label)
                and str(widget.cget("text")).startswith("截图")
                for widget in walk(app._tray_menu)
            ),
            "托盘菜单包含「截图」入口",
        )
        children = app._capture_menu_children()
        check(
            any(
                "区域截图" in str(item[0]) and "Ctrl+Alt+A" in str(item[0])
                for item in children
                if isinstance(item, tuple)
            ),
            "托盘截图子菜单显示当前快捷键",
        )
        if parent_row is not None:
            app._open_submenu(parent_row, [("明天 08:00 关机", lambda: None)])
            app.update_idletasks()
            check(app._submenu is not None, "二级菜单可展开")
            app._close_tray_menu()
            check(app._submenu is None and app._tray_menu is None, "菜单可关闭")
    except Exception as exc:  # noqa: BLE001
        check(False, f"托盘菜单异常：{exc}")

    # 倒计时循环提醒（真实走一遍：设定 → 响 → 再计时 → 用完结束）
    try:
        from datetime import datetime, timedelta
        from tkinter import messagebox as mb

        import fk.ui.alarm as alarm_ui

        page = app.pages["alarm"]
        app.show_page("alarm")
        page.sound_var.set(False)
        page.dialog_var.set(True)
        page.repeat_var.set(True)
        page.repeat_mode_var.set("count")
        page.repeat_count_var.set("3")
        page.hours_var.set("0")
        page.minutes_var.set("0")
        page.seconds_var.set("5")

        original_ask = mb.askyesno
        original_dialog = alarm_ui.ReminderDialog
        mb.askyesno = lambda *a, **k: True
        alarm_ui.ReminderDialog = lambda *a, **k: None
        try:
            page._start_countdown()
            alarm = app.config.alarm or {}
            check(
                alarm.get("repeat") == "count" and alarm.get("repeat_total") == 3,
                f"循环次数已记录（{alarm.get('repeat')}/{alarm.get('repeat_total')}）",
            )
            check(alarm.get("interval_seconds") == 5, "循环间隔等于倒计时长度")

            for _ in range(2):
                current = app.config.alarm
                current["target"] = (datetime.now() - timedelta(seconds=1)).strftime(
                    "%Y-%m-%dT%H:%M:%S"
                )
                app.config.set_alarm(current)
                page._tick()

            alarm = app.config.alarm or {}
            check(alarm.get("fired") == 2, f"已响 2 次（fired={alarm.get('fired')}）")
            check(bool(alarm) and alarm_mod.is_active(alarm), "次数未用完 → 继续计时")

            current = app.config.alarm
            current["target"] = (datetime.now() - timedelta(seconds=1)).strftime(
                "%Y-%m-%dT%H:%M:%S"
            )
            app.config.set_alarm(current)
            page._tick()
            check(app.config.alarm is None, "次数用完后自动结束")
        finally:
            mb.askyesno = original_ask
            alarm_ui.ReminderDialog = original_dialog
            app.config.clear_alarm()
            page.repeat_var.set(False)
            page._refresh_status()
    except Exception as exc:  # noqa: BLE001
        check(False, f"循环提醒异常：{exc}")

    # 托盘快捷关机（用假的 arm，绝对不真的关机）
    try:
        from datetime import datetime

        from fk import shutdown as sdm

        calls = []
        from tkinter import messagebox as mb

        original_arm = sdm.arm
        original_ask = mb.askyesno
        mb.askyesno = lambda *a, **k: True

        def fake_arm(target, comment="", replace_existing=False):
            calls.append(target)
            return True, ""

        sdm.arm = fake_arm
        try:
            app._quick_shutdown("hours10")
            check(len(calls) == 1, "托盘「10 小时后关机」调用了系统接口")
            if calls:
                hours = (calls[0] - datetime.now()).total_seconds() / 3600
                check(9.9 < hours <= 10.01, f"目标时间约 10 小时后（{hours:.2f}）")
            check(app.config.shutdown_plan is not None, "关机计划已写入配置")
        finally:
            sdm.arm = original_arm
            mb.askyesno = original_ask
            app.config.shutdown_plan = None
            app.pages["shutdown"]._refresh_status()
    except Exception as exc:  # noqa: BLE001
        check(False, f"托盘关机快捷异常：{exc}")

    # 任务编辑对话框（新建 / 编辑）
    try:
        from fk.ui.tasks import TaskDialog

        dialog = TaskDialog(app, None, lambda _t, _n: None)
        dialog.withdraw()
        dialog.update_idletasks()
        dialog.destroy()
        check(True, "新建任务对话框可构建")
    except Exception as exc:  # noqa: BLE001
        check(False, f"新建任务对话框失败：{exc}")

    # 新任务可选“5 分钟后首次备份”
    try:
        from datetime import datetime

        from fk.ui.tasks import TaskDialog

        captured = {}
        dialog = TaskDialog(
            app, None, lambda task, is_new: captured.update(task=task, new=is_new)
        )
        dialog.withdraw()
        dialog.name_var.set("首次备份选项测试")
        dialog.sources = [str(src)]
        dialog._refresh_sources()
        dialog.first_run_var.set("after5")
        dialog._save()
        task = captured.get("task")
        check(task is not None, "首次备份选项任务已提交")
        if task is not None:
            check(bool(task.bootstrap_at), "5 分钟首次备份时间已写入")
            target = datetime.strptime(task.bootstrap_at, "%Y-%m-%dT%H:%M:%S")
            seconds = (target - datetime.now()).total_seconds()
            check(240 <= seconds <= 310, f"首次备份约 5 分钟后（{seconds:.0f} 秒）")
    except Exception as exc:  # noqa: BLE001
        check(False, f"首次备份选项异常：{exc}")

    # 任务目标/名称冲突校验
    try:
        from fk.config import Task as TaskModel
        from fk.ui.tasks import TaskDialog

        existing = TaskModel(
            id="t_existing",
            name="已有任务",
            sources=[str(src)],
            target=str(tmp / "已有目标"),
        )
        app.config.tasks.append(existing)
        dialog = TaskDialog(app, None, lambda _t, _n: None)
        dialog.withdraw()
        problem_same = dialog._validate([str(src)], str(tmp / "已有目标"))
        problem_nested = dialog._validate([str(src)], str(tmp / "已有目标" / "sub"))
        dialog.name_var.set("已有任务")
        problem_name = dialog._validate([str(src)], str(tmp / "另一个目标"))
        dialog.destroy()
        app.config.tasks.remove(existing)
        check(bool(problem_same) and "相同" in problem_same, "相同目标被拒绝")
        check(bool(problem_nested) and "包含" in problem_nested, "嵌套目标被拒绝")
        check(bool(problem_name) and "已经存在" in problem_name, "重复任务名被拒绝")
    except Exception as exc:  # noqa: BLE001
        check(False, f"任务冲突校验异常：{exc}")

    # 任务对话框改主备份目录只暂存，取消不会改全局设置
    try:
        import fk.ui.tasks as tasks_ui

        original_dir = app.config.settings.backup_root
        original_pick = tasks_ui.filedialog.askdirectory
        dialog = tasks_ui.TaskDialog(app, None, lambda _t, _n: None)
        dialog.withdraw()
        tasks_ui.filedialog.askdirectory = lambda *a, **k: str(tmp / "暂存的新主目录")
        try:
            dialog._change_master()
        finally:
            tasks_ui.filedialog.askdirectory = original_pick
        check(
            app.config.settings.backup_root == original_dir,
            "改主备份目录在保存任务前不写全局设置",
        )
        dialog.destroy()
    except Exception as exc:  # noqa: BLE001
        check(False, f"主备份目录暂存异常：{exc}")

    # 隐藏项选择器：任务对话框接入 + 默认显示隐藏项 + 可关闭
    try:
        import fk.ui.tasks as tasks_mod
        from fk.ui.picker import HiddenAwarePicker
        from fk.ui.tasks import TaskDialog

        hidden_dir = tmp / "隐藏目录"
        hidden_dir.mkdir()
        hidden_file = tmp / ".hidden_测试.txt"
        hidden_file.write_text("hidden", encoding="utf-8")

        original_pick = tasks_mod.pick_paths

        def fake_pick(_parent, mode="files", initial_dir=None):
            return [str(hidden_dir if mode == "folders" else hidden_file)]

        tasks_mod.pick_paths = fake_pick
        dialog = TaskDialog(app, None, lambda _t, _n: None)
        dialog.withdraw()
        try:
            dialog._add_folder()
            check(str(hidden_dir) in dialog.sources, "添加隐藏文件夹接入任务来源")
            dialog._add_files()
            check(str(hidden_file) in dialog.sources, "添加隐藏文件接入任务来源")
        finally:
            tasks_mod.pick_paths = original_pick
            dialog.grab_release()
            dialog.destroy()

        HiddenAwarePicker._last_show_hidden = True
        picker = HiddenAwarePicker(app, mode="files", initial_dir=str(tmp))
        picker.withdraw()
        end = time.time() + 3.0
        while time.time() < end and not picker.tree.get_children():
            app.update()
            time.sleep(0.02)
        names = [
            str(picker.tree.item(item, "values")[0])
            for item in picker.tree.get_children()
        ]
        check(".hidden_测试.txt" in names, "选择器默认显示隐藏文件")
        picker.show_hidden_var.set(False)
        picker._on_filter_change()
        names = [
            str(picker.tree.item(item, "values")[0])
            for item in picker.tree.get_children()
        ]
        check(".hidden_测试.txt" not in names, "关闭“显示隐藏项”后隐藏文件消失")
        HiddenAwarePicker._last_show_hidden = True
        picker._cancel()
    except Exception as exc:  # noqa: BLE001
        check(False, f"隐藏项选择器异常：{exc}")

    try:
        from fk.config import Task as TaskModel
        from fk.ui.tasks import TaskDialog

        sample = TaskModel(id="t_dlg", name="示例", sources=[str(src)], target=str(tmp / "x"))
        sample.mode = "pick"
        sample.pick_exts = [".zip"]
        dialog = TaskDialog(app, sample, lambda _t, _n: None)
        dialog.withdraw()
        dialog.update_idletasks()
        dialog.destroy()
        check(True, "智能挑选任务对话框可构建")
    except Exception as exc:  # noqa: BLE001
        check(False, f"智能挑选对话框失败：{exc}")

    # 主备份文件夹 + 自动子目录
    try:
        from fk.ui.tasks import TaskDialog

        master = tmp / "主备份文件夹"
        app.config.settings.backup_root = str(master)
        saved: dict = {}
        dialog = TaskDialog(app, None, lambda task, is_new: saved.update(task=task, new=is_new))
        dialog.withdraw()
        dialog.name_var.set("自动测试任务")
        dialog.sources = [str(src)]
        dialog._refresh_sources()
        dialog._save()
        task = saved.get("task")
        expected = str(master / "自动测试任务")
        check(task is not None, "对话框保存成功")
        check(
            task is not None and task.target == expected,
            f"目标自动生成为 主备份文件夹/任务名（{task.target if task else None}）",
        )
        check(Path(expected).exists(), "任务子文件夹已创建")
    except Exception as exc:  # noqa: BLE001
        check(False, f"自动目标生成失败：{exc}")

    # 端到端备份
    task = Task(
        id="t_ui",
        name="UI 测试任务",
        sources=[str(src)],
        target=str(tmp / "backup" / "ui"),
        mode="mirror",
        schedule=Schedule(type="off"),
    )
    cfg.add_task(task)
    app.show_page("tasks")
    app.backup_task(task.id)

    deadline = time.time() + 20
    while time.time() < deadline and app.runner.is_busy():
        app.update()
        time.sleep(0.05)
    app.update()

    target = tmp / "backup" / "ui"
    check((target / "readme.txt").exists(), "界面触发的备份已写入目标")
    check((target / "docs" / "note.md").exists(), "子目录也被备份")
    check(bool(cfg.history), f"历史记录已生成（{len(cfg.history)} 条）")
    check(cfg.history[0].status == "success", f"记录状态：{cfg.history[0].status_label}")

    app.show_page("home")
    app.update_idletasks()
    check(True, "备份后刷新页面无异常")

    # 过期提醒不能静默消失，要提示“已错过”
    try:
        from datetime import datetime, timedelta

        import fk.ui.alarm as alarm_ui
        from fk import alarm as alarm_mod

        original_info = alarm_ui.messagebox.showinfo
        notices = []
        alarm_ui.messagebox.showinfo = lambda *a, **k: notices.append((a, k))
        app.config.set_alarm(
            alarm_mod.make_alarm(
                datetime.now() - timedelta(minutes=3),
                "countdown",
                sound=False,
                dialog=True,
                label="过期测试",
            )
        )
        page = app.pages["alarm"]
        page._refresh_status()
        end = time.time() + 1.0
        while time.time() < end and not notices:
            app.update()
            time.sleep(0.02)
        check(bool(notices), "过期提醒会提示已错过")
        check(app.config.alarm is None, "提示后清除过期提醒")
    except Exception as exc:  # noqa: BLE001
        check(False, f"过期提醒处理异常：{exc}")
    finally:
        try:
            alarm_ui.messagebox.showinfo = original_info
            app.config.clear_alarm()
            app.pages["alarm"]._refresh_status()
        except Exception:
            pass

    # 设置页刷新会同步全部勾选项
    try:
        settings_page = app.pages["settings"]
        app.config.settings.notify = False
        app.config.settings.delete_extraneous = True
        settings_page.refresh()
        check(settings_page.notify_var.get() is False, "设置页刷新通知开关")
        check(settings_page.extraneous_var.get() is True, "设置页刷新镜像清理开关")
    except Exception as exc:  # noqa: BLE001
        check(False, f"设置页刷新异常：{exc}")

    # 托盘 tooltip 真正发出更新消息
    try:
        from fk.tray import WM_UPDATE_TIP, TrayIcon

        tray = TrayIcon()
        posted = []
        tray._post = lambda message: posted.append(message)
        tray.set_tooltip("测试提示")
        check(WM_UPDATE_TIP in posted, "set_tooltip 发出更新提示消息")
    except Exception as exc:  # noqa: BLE001
        check(False, f"托盘提示更新异常：{exc}")

    # 有关机计划时退出要弹窗确认（继续退出 / 取消退出）
    try:
        from datetime import datetime, timedelta

        import fk.ui.shutdown as shutdown_ui
        from fk import shutdown as sdm

        app.config.shutdown_plan = sdm.make_plan(
            datetime.now() + timedelta(hours=3), "hours10"
        )
        check(app.shutdown_active(), "关机计划处于有效状态")

        dialog = shutdown_ui.ExitShutdownDialog(app, app.config.shutdown_plan)
        dialog.withdraw()
        dialog.update_idletasks()
        check(dialog.result == "abort", "弹窗默认结果是「取消退出」")
        rows = dialog._rows()
        names = [name for name, _value in rows]
        check("关机时间" in names, f"弹窗显示关机时间（{names}）")
        check("剩余时间" in names, "弹窗显示剩余时间")
        check("设定方式" in names, "弹窗显示设定方式")
        dialog._choose(dialog.CONTINUE)
        check(dialog.result == "continue", "可以选「继续退出」")

        # 选「取消退出」时不退出
        original_ask = shutdown_ui.ask_exit_with_shutdown
        shutdown_ui.ask_exit_with_shutdown = lambda _app: "abort"
        try:
            app.quit_app()
            check(not app._closed, "选「取消退出」后程序仍在运行")
            check(app.config.shutdown_plan is not None, "选「取消退出」时关机计划保留")
        finally:
            shutdown_ui.ask_exit_with_shutdown = original_ask

        # 选「取消并退出」时既要取消计划也要退出：先验证取消逻辑不动计划位
        from fk import shutdown as sdm2

        check(sdm2.plan_target(app.config.shutdown_plan) is not None, "计划目标可读")

        # 有关机计划 + 备份进行中：提示无法退出，且计划保持不变
        from tkinter import messagebox as mb2

        original_busy = app.runner.is_busy
        original_warning = mb2.showwarning
        warnings = []
        app.runner.is_busy = lambda: True
        mb2.showwarning = lambda *a, **k: warnings.append((a, k))
        shutdown_ui.ask_exit_with_shutdown = lambda _app: "continue"
        try:
            app.quit_app()
            check(not app._closed, "备份进行中（有关机计划）无法退出")
            check(bool(warnings), "备份进行中会弹出无法退出提示")
            check(app.config.shutdown_plan is not None, "无法退出时关机计划保持不变")
        finally:
            app.runner.is_busy = original_busy
            mb2.showwarning = original_warning
            shutdown_ui.ask_exit_with_shutdown = original_ask
    except Exception as exc:  # noqa: BLE001
        check(False, f"退出确认弹窗异常：{exc}")

    # 选「继续退出」走正常退出流程，关机计划保持不变
    try:
        import fk.ui.shutdown as shutdown_ui2

        original_ask2 = shutdown_ui2.ask_exit_with_shutdown
        shutdown_ui2.ask_exit_with_shutdown = lambda _app: "continue"
        try:
            app.quit_app()
        finally:
            shutdown_ui2.ask_exit_with_shutdown = original_ask2
        check(app._closed, "选「继续退出」后程序正常退出（含托盘清理）")
        check(app.config.shutdown_plan is not None, "退出软件不取消关机计划")
    except Exception as exc:  # noqa: BLE001
        check(False, f"退出流程异常：{exc}")

    print("\n" + "=" * 60)
    print(f"通过 {PASSED} 项，失败 {FAILED} 项")
    print("=" * 60)
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
