"""主窗口。"""
from __future__ import annotations

import json
import queue
import time
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .. import theme
from ..backup import Progress, Result
from ..config import Config
from ..hotkeys import (
    ACTION_BY_ID,
    ACTIONS,
    STATUS_FAILED,
    ApplyResult,
    HotkeyRegistry,
    RegisterResult,
    log as hotkey_log,
    normalize_config,
)
from ..paths import APP_TAGLINE, APP_TITLE, APP_VERSION, app_icon
from ..runner import BackupRunner
from ..scheduler import Scheduler
from ..theme import C, font, sp
from ..tray import TrayIcon
from ..widgets import (
    FlatButton,
    ICONS,
    StatusDot,
    install_wheel_router,
    label,
)

NAV_ITEMS = [
    ("shutdown", "定时关机", "power"),
    ("alarm", "时间闹钟", "alarm"),
    ("timers", "计时器", "timer"),
    ("shot", "快速截图", "camera"),
    ("tasks", "备份任务", "tasks"),
    ("settings", "设置", "settings"),
]


class StatusPill(tk.Frame):
    def __init__(self, master):
        super().__init__(
            master,
            bg=C.CARD,
            highlightthickness=1,
            highlightbackground=C.BORDER,
            bd=0,
        )
        self.dot = StatusDot(self, C.TEXT_MUTED, 7, bg=C.CARD)
        self.dot.pack(side="left", padx=(sp(11), sp(7)), pady=sp(8))
        self.text = label(self, "空闲", 9, C.TEXT_DIM, bg=C.CARD)
        self.text.pack(side="left", padx=(0, sp(12)), pady=sp(8))

    def set(self, text: str, color: str) -> None:
        self.text.configure(text=text, fg=color)
        self.dot.set_color(color)


class StatusBar(tk.Frame):
    def __init__(self, master, app):
        super().__init__(master, bg=C.BG_DEEP, height=sp(46))
        self.app = app
        self._persist = False
        self._cancel_action = None
        self.pack_propagate(False)

        self.msg = label(self, "就绪", 9, C.TEXT_DIM, bg=C.BG_DEEP)
        self.msg.pack(side="left", padx=(sp(26), sp(14)), pady=sp(12))

        self.cancel = FlatButton(
            self, "取消", command=self._cancel, kind="subtle", padx=12, pady=4, font_size=9
        )

        self.bar = ttk.Progressbar(
            self,
            orient="horizontal",
            mode="determinate",
            style="Bar.Horizontal.TProgressbar",
            length=sp(240),
        )

        self.right = tk.Frame(self, bg=C.BG_DEEP)
        self.right.pack(side="right", padx=(sp(10), sp(26)))

    def _cancel(self) -> None:
        if self._cancel_action is not None:
            try:
                self._cancel_action()
            except Exception:
                pass
            self.set_message("正在取消…", "warn")
            return
        self.app.runner.cancel()
        self.set_message("正在取消…", "warn")

    def set_cancel_action(self, action) -> None:
        """让状态栏的取消按钮临时指向备份之外的任务（如还原）。"""
        self._cancel_action = action

    def set_message(self, text: str, kind: str = "info", persist: bool = False) -> None:
        self._persist = persist
        color = {
            "info": C.TEXT_DIM,
            "ok": C.GREEN,
            "warn": C.AMBER,
            "error": C.RED,
        }.get(kind, C.TEXT_DIM)
        self.msg.configure(text=text, fg=color)

    def start(self, text: str) -> None:
        self.set_message(text, "info")
        if not self.bar.winfo_ismapped():
            self.bar.pack(side="left", padx=0, pady=18, fill="x", expand=True)
        if not self.cancel.winfo_ismapped():
            self.cancel.pack(side="right", padx=(10, 12), pady=10)
        self.bar.stop()
        self.bar.configure(mode="determinate", maximum=100, value=0)

    def progress(self, progress: Progress) -> None:
        if not self.bar.winfo_ismapped():
            self.start("正在备份…")
        self.bar.configure(value=progress.percent)
        detail = progress.detail or progress.current
        if detail:
            self.set_message(detail, "info")

    def indeterminate(self, text: str) -> None:
        self.set_message(text, "info")
        if not self.bar.winfo_ismapped():
            self.bar.pack(side="left", padx=0, pady=18, fill="x", expand=True)
        self.bar.configure(mode="indeterminate")
        self.bar.start(14)

    def idle(self) -> None:
        self.bar.stop()
        self.bar.pack_forget()
        self.cancel.pack_forget()
        if not getattr(self, "_persist", False):
            self.set_message("就绪", "info")


class TrayHotkeyBackend:
    """把托盘线程的同步 RegisterHotKey 封装成注册表后端。"""

    def __init__(self, tray: TrayIcon):
        self.tray = tray

    def register(self, modifiers: int, vk: int) -> RegisterResult:
        ok, hotkey_id, error = self.tray.try_register_hotkey(modifiers, vk)
        return RegisterResult(ok, hotkey_id, error)

    def unregister(self, hotkey_id: int) -> tuple[bool, int]:
        return self.tray.try_unregister_hotkey(hotkey_id)


class App(tk.Tk):
    def __init__(self, config: Config, start_minimized: bool | None = None):
        super().__init__()
        self.config = config
        self.events: queue.Queue = queue.Queue()
        self.pages: dict[str, object] = {}
        self.nav_buttons: dict[str, object] = {}
        self.current_page = ""
        self._closed = False
        self._size_cache: tuple[int, float] = (-1, 0.0)
        self._start_hidden = bool(start_minimized) or bool(config.settings.start_minimized)

        theme.setup(self)
        self.title(f"{APP_TITLE} · {APP_TAGLINE}")
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        win_w = min(sp(1240), max(sp(900), screen_w - sp(80)))
        win_h = min(sp(830), max(sp(620), screen_h - sp(100)))
        self.geometry(f"{win_w}x{win_h}+{(screen_w - win_w) // 2}+{max(0, (screen_h - win_h) // 3)}")
        self.minsize(sp(960), sp(620))
        self.configure(bg=C.BG)
        try:
            if app_icon().exists():
                self.iconbitmap(default=str(app_icon()))
        except Exception:
            pass

        install_wheel_router(self)
        self._ensure_backup_root()
        self._sync_autostart()
        self._prune_shutdown_plan()

        self.runner = BackupRunner(config, self.events)
        self.scheduler = Scheduler(config, self._on_schedule_due)

        self.auto_paused = False
        self.tray: TrayIcon | None = None
        self.hotkey_registry: HotkeyRegistry | None = None
        self._last_hotkey_trigger: dict[str, float] = {}
        self._hotkey_problems_announced = False
        self._tray_menu: tk.Toplevel | None = None
        self._submenu: tk.Toplevel | None = None
        self._submenu_owner = None
        self._submenu_close = None
        self._tray_focus_job = None
        self._tray_hint_shown = False
        self._hidden = False

        self._build()
        self.scheduler.start()
        self.show_page("shutdown")
        self.after(150, self._pump)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._init_tray()

    def report_callback_exception(self, exc, val, tb) -> None:
        """Tk 回调异常统一落盘并在状态栏提示，避免窗口版静默失败。"""
        text = "".join(traceback.format_exception(exc, val, tb))
        try:
            hotkey_log("界面回调异常：\n" + text)
        except Exception:
            pass
        try:
            self.status.set_message(f"操作失败：{val}", "error")
        except Exception:
            pass

    # ------------------------------------------------------------ 布局
    def _ensure_backup_root(self) -> None:
        """确保主备份文件夹存在（默认在最后一个盘符下）。"""
        root = self.config.settings.backup_root
        if not root:
            return
        try:
            from ..saveutils import is_network_path

            if is_network_path(root):
                # 网络路径放到第一次备份/手动打开时再创建，避免启动被断开的共享拖住
                return
            Path(root).mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

    def _build(self) -> None:
        self.grid_columnconfigure(0, minsize=sp(232))
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        sidebar = tk.Frame(self, bg=C.SIDEBAR, width=sp(232))
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        self._build_sidebar(sidebar)

        main = tk.Frame(self, bg=C.BG)
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_rowconfigure(1, weight=1)
        main.grid_columnconfigure(0, weight=1)

        self._build_topbar(main)

        self.content = tk.Frame(main, bg=C.BG)
        self.content.grid(row=1, column=0, sticky="nsew")

        self.status = StatusBar(main, self)
        self.status.grid(row=2, column=0, sticky="ew")

        self._build_pages()

    def _build_sidebar(self, parent: tk.Frame) -> None:
        brand = tk.Frame(parent, bg=C.SIDEBAR, height=sp(96))
        brand.pack(fill="x")
        brand.pack_propagate(False)

        logo = ICONS.get("logo", base=40)
        holder = tk.Frame(brand, bg=C.SIDEBAR)
        holder.pack(side="left", padx=(sp(18), sp(12)), pady=(sp(24), 0))
        if logo is not None:
            self._logo_ref = logo
            tk.Label(holder, image=logo, bg=C.SIDEBAR, bd=0).pack()
        else:
            tk.Label(
                holder, text="▣", font=font(18, "bold"), fg=C.ACCENT, bg=C.SIDEBAR
            ).pack()

        text_holder = tk.Frame(brand, bg=C.SIDEBAR)
        text_holder.pack(side="left", pady=(sp(30), 0))
        label(text_holder, APP_TITLE, 13, C.TEXT, "bold", bg=C.SIDEBAR).pack(anchor="w")
        label(text_holder, f"v{APP_VERSION}", 8, C.TEXT_MUTED, bg=C.SIDEBAR).pack(
            anchor="w", pady=(sp(2), 0)
        )

        nav = tk.Frame(parent, bg=C.SIDEBAR)
        nav.pack(fill="x", pady=(sp(6), 0))
        for key, text, icon_name in NAV_ITEMS:
            from ..widgets import NavButton

            button = NavButton(nav, key, text, icon_name, self.show_page)
            button.pack(fill="x")
            self.nav_buttons[key] = button

        footer = tk.Frame(parent, bg=C.SIDEBAR)
        footer.pack(side="bottom", fill="x", padx=sp(18), pady=sp(20))

        tk.Frame(footer, bg=C.BORDER_SOFT, height=1).pack(fill="x", pady=(0, sp(14)))
        label(footer, "备份位置", 8, C.TEXT_MUTED, bg=C.SIDEBAR).pack(anchor="w")
        self.side_path = label(footer, "—", 9, C.TEXT_DIM, bg=C.SIDEBAR, anchor="w")
        self.side_path.pack(anchor="w", pady=(sp(3), sp(10)), fill="x")
        self.side_bar = ttk.Progressbar(
            footer, orient="horizontal", mode="determinate", style="Bar.Horizontal.TProgressbar"
        )
        self.side_bar.pack(fill="x")
        self.side_usage = label(footer, "—", 8, C.TEXT_MUTED, bg=C.SIDEBAR, anchor="w")
        self.side_usage.pack(anchor="w", pady=(sp(6), 0))

        FlatButton(
            footer,
            "一键备份全部",
            command=self.backup_all,
            kind="primary",
            padx=10,
            pady=9,
            font_size=9,
            bold=True,
        ).pack(fill="x", pady=(sp(18), 0))

        self._refresh_sidebar()

    def _build_topbar(self, parent: tk.Frame) -> None:
        bar = tk.Frame(parent, bg=C.BG, height=sp(96))
        bar.grid(row=0, column=0, sticky="ew")
        bar.grid_propagate(False)
        bar.grid_columnconfigure(1, weight=1)

        left = tk.Frame(bar, bg=C.BG)
        left.grid(row=0, column=0, sticky="w", padx=(sp(26), 0), pady=(sp(18), 0))
        self.title_label = label(left, "", 16, C.TEXT, "bold", bg=C.BG)
        self.title_label.pack(anchor="w")
        self.subtitle_label = label(left, "", 9, C.TEXT_MUTED, bg=C.BG)
        self.subtitle_label.pack(anchor="w", pady=(sp(4), 0))

        right = tk.Frame(bar, bg=C.BG)
        right.grid(row=0, column=2, sticky="e", padx=(0, sp(26)), pady=(sp(22), 0))
        self.pill = StatusPill(right)
        self.pill.pack(side="left", padx=(0, sp(12)))
        self.btn_backup_all = FlatButton(right, "立即备份全部", command=self.backup_all)
        self.btn_backup_all.pack(side="left")

    def _build_pages(self) -> None:
        from .alarm import AlarmPage
        from .screenshot import ShotPage
        from .settings import SettingsPage
        from .shutdown import ShutdownPage
        from .tasks import TasksPage
        from .timers import TimersPage

        self.pages = {
            "shutdown": ShutdownPage(self.content, self),
            "alarm": AlarmPage(self.content, self),
            "timers": TimersPage(self.content, self),
            "shot": ShotPage(self.content, self),
            "tasks": TasksPage(self.content, self),
            "settings": SettingsPage(self.content, self),
        }

    # ------------------------------------------------------------ 导航
    def show_page(self, key: str) -> None:
        page = self.pages.get(key)
        if page is None:
            return
        for other in self.pages.values():
            other.pack_forget()
        page.pack(fill="both", expand=True)
        self.current_page = key
        self.title_label.configure(text=page.title)
        self.subtitle_label.configure(text=page.subtitle)
        for nav_key, button in self.nav_buttons.items():
            button.set_active(nav_key == key)
        try:
            page.on_show()
        except Exception as exc:  # noqa: BLE001 - 页面刷新失败不应导致崩溃
            self.status.set_message(f"页面加载出错：{exc}", "error")

    # ------------------------------------------------------------ 备份动作
    def backup_all(self) -> None:
        tasks = list(self.config.enabled_tasks())
        if not tasks:
            if self.tray is not None and not self.is_visible():
                self.tray.notify("没有启用的备份任务", "请打开主窗口，在「备份任务」中启用或新建任务。")
            else:
                messagebox.showinfo(
                    "没有启用的任务", "请先在「备份任务」中启用或新建一个备份任务。", parent=self
                )
            return
        count = self.runner.enqueue([t.id for t in tasks], manual=True)
        if count:
            self.status.set_message(f"已加入队列：{count} 个任务", "info")
        else:
            self.status.set_message("任务已在队列中", "warn")

    def backup_task(self, task_id: str) -> None:
        task = self.config.get_task(task_id)
        if task is None:
            return
        count = self.runner.enqueue([task_id], manual=True)
        if count:
            self.status.set_message(f"已开始备份：{task.name}", "info")
        else:
            self.status.set_message(f"「{task.name}」正在队列中", "warn")

    def _on_schedule_due(self, task) -> None:
        self.events.put(("scheduled", task.id))

    # ------------------------------------------------------------ 事件泵
    def _pump(self) -> None:
        if self._closed:
            return
        if self.tray is not None:
            try:
                while True:
                    kind = self.tray.poll()
                    if kind is None:
                        break
                    if kind == "toggle":
                        self.toggle_window()
                    elif kind == "show":
                        self.show_window()
                    elif kind == "menu":
                        self._show_tray_menu()
                    elif kind.startswith("hotkey:"):
                        try:
                            hotkey_id = int(kind.split(":", 1)[1])
                        except (IndexError, ValueError):
                            hotkey_id = 0
                        if hotkey_id:
                            self._on_hotkey_trigger(hotkey_id)
            except Exception:
                pass
        try:
            while True:
                event = self.events.get_nowait()
                try:
                    self._handle(event)
                except Exception as exc:  # noqa: BLE001
                    self.status.set_message(f"处理事件出错：{exc}", "error")
        except queue.Empty:
            pass
        try:
            self.after(150, self._pump)
        except tk.TclError:
            pass

    def _handle(self, event) -> None:
        kind = event[0]
        if kind == "scheduled":
            if self.auto_paused:
                return
            self.runner.enqueue([event[1]], manual=False)
            return
        if kind == "log":
            try:
                hotkey_log(str(event[1]))
            except Exception:
                pass
            return
        if kind == "start":
            _, task_id, name, manual = event
            self.pill.set(f"正在备份 · {name}", C.ACCENT)
            self.status.start(f"正在备份：{name}")
            self._update_tray_tooltip()
            for page in self.pages.values():
                page.on_backup_event("start", (task_id, name, manual))
            return
        if kind == "progress":
            _, task_id, progress = event
            self.status.progress(progress)
            for page in self.pages.values():
                page.on_backup_event("progress", (task_id, progress))
            return
        if kind == "done":
            _, task_id, result, manual = event
            if self.config.last_save_error:
                hotkey_log(f"备份结果写入配置失败：{self.config.last_save_error}")
                self.status.set_message(
                    f"备份完成，但配置保存失败：{self.config.last_save_error}", "error", persist=True
                )
            else:
                self.status.set_message(
                    f"备份完成：{result.summary}", "ok" if result.ok else "error", persist=True
                )
            for page in self.pages.values():
                page.on_backup_event("done", (task_id, result, manual))
            self.refresh_all()
            self._refresh_sidebar()
            task = self.config.get_task(task_id)
            task_name = task.name if task else "备份任务"
            if self.tray is not None and not self.is_visible():
                if result.ok:
                    self.tray.notify("备份完成", f"{task_name}：{result.summary}")
                elif result.status != "cancelled":
                    self.tray.notify("备份未成功", f"{task_name}：{result.summary}")
            if (
                manual
                and self.config.settings.notify
                and result.status in ("failed", "partial")
                and self.is_visible()
            ):
                details = "\n".join(result.errors[:5])
                messagebox.showwarning(
                    "备份未完全成功",
                    f"{result.summary}\n\n{details}",
                    parent=self,
                )
            return
        if kind == "idle":
            if self.auto_paused:
                self.pill.set("已暂停自动备份", C.AMBER)
            else:
                self.pill.set("空闲", C.TEXT_MUTED)
            self.status.idle()
            self._update_tray_tooltip()

    def refresh_all(self) -> None:
        page = self.pages.get("tasks")
        if page is None:
            return
        try:
            page.refresh()
        except Exception:
            pass

    # ------------------------------------------------------------ 侧栏信息
    def _refresh_sidebar(self) -> None:
        root = self.config.settings.backup_root or "未设置"
        display = root
        if len(display) > 26:
            display = "…" + display[-25:]
        try:
            self.side_path.configure(text=display)
        except tk.TclError:
            return

        from pathlib import Path

        from ..fsutil import disk_usage, human_size

        if getattr(self, "_sidebar_probe_running", False):
            return
        self._sidebar_probe_running = True

        def work():
            probe = root if root and root != "未设置" else "C:\\"
            if not Path(probe).exists():
                anchor = Path(probe).anchor
                probe = anchor if anchor and Path(anchor).exists() else "C:\\"
            return disk_usage(probe)

        def done(kind, value):
            self._sidebar_probe_running = False
            if kind != "ok":
                return
            total, free = value
            try:
                if total:
                    used_pct = 100.0 * (total - free) / total
                    self.side_bar.configure(value=max(0.0, min(100.0, used_pct)))
                    self.side_usage.configure(
                        text=f"可用 {human_size(free)} / 共 {human_size(total)}"
                    )
                else:
                    self.side_bar.configure(value=0)
                    self.side_usage.configure(text="无法读取磁盘信息")
            except tk.TclError:
                pass

        from ..widgets import run_bg

        run_bg(self, work, done)

    def backup_bytes(self, callback=None) -> None:
        """后台统计备份总占用。"""
        import time

        value, stamp = self._size_cache
        if value >= 0 and time.monotonic() - stamp < 60:
            if callback:
                callback(value)
            return

        def work():
            return self.config.total_backup_bytes()

        def done(kind, result):
            if kind == "ok":
                self._size_cache = (int(result), time.monotonic())
                if callback:
                    callback(int(result))
            elif callback:
                callback(-1)

        from ..widgets import run_bg

        run_bg(self, work, done)

    # ------------------------------------------------------------ 托盘
    def _init_tray(self) -> None:
        try:
            self.tray = TrayIcon(APP_TITLE, app_icon())
            if not self.tray.start():
                self.tray = None
        except Exception:
            self.tray = None
        self._update_tray_tooltip()
        if self.tray is not None and self._start_hidden:
            self.after(400, self.hide_window)

        if self.tray is None:
            self.hotkey_registry = None
            self._refresh_hotkey_ui()
            self.after(900, self._announce_hotkey_problems)
            return

        try:
            self.hotkey_registry = HotkeyRegistry(
                TrayHotkeyBackend(self.tray),
                config=self.config.capture_hotkeys,
                on_change=self._on_hotkeys_changed,
            )
            for warning in self.hotkey_registry.warnings_list:
                hotkey_log(f"快捷键配置：{warning}")
            self.hotkey_registry.start()
        except Exception as exc:  # noqa: BLE001
            hotkey_log(f"初始化截图快捷键失败：{exc}")
            self.hotkey_registry = None
        self._refresh_hotkey_ui()
        self.after(900, self._announce_hotkey_problems)

    def _on_hotkeys_changed(self) -> None:
        self._refresh_hotkey_ui()

    def _announce_hotkey_problems(self) -> None:
        """启动后非阻塞提示注册失败/配置损坏（R-4.7、R-8.4）。"""
        if self._closed or self._hotkey_problems_announced:
            return
        self._hotkey_problems_announced = True

        if self.config.load_error:
            hotkey_log(self.config.load_error)
            if self.tray is not None:
                self.tray.notify("配置读取失败", self.config.load_error)
            self.status.set_message(self.config.load_error, "error")

        for warning in self.config.capture_hotkey_warnings or []:
            hotkey_log(f"快捷键配置：{warning}")
        if self.config.capture_hotkey_warnings and not self.config.load_error:
            self.status.set_message(
                "部分快捷键配置无效，已降级为未启用；详情见 app.log", "warn"
            )

        failures = self.hotkey_registry.failures() if self.hotkey_registry else []
        if not failures:
            return
        labels = "、".join(
            f"{ACTION_BY_ID[state.action].label}（{state.binding.text or '未设置'}）"
            for state in failures
        )
        region_failed = any(
            state.action == "capture.region" for state in failures
        )
        message = (
            f"{labels} 注册失败，可能已被系统或其他程序占用。"
            "可在「快速截图」页修改快捷键；托盘菜单和页面按钮仍可截图。"
        )
        if region_failed and self.tray is not None:
            self.tray.notify("区域截图快捷键不可用", message)
        self.status.set_message(message, "warn")

    # ------------------------------------------------------------ 截图快捷键
    def _refresh_hotkey_ui(self) -> None:
        page = self.pages.get("shot") if getattr(self, "pages", None) else None
        if page is not None:
            try:
                page.refresh_hotkeys()
            except Exception:
                pass
        settings = self.pages.get("settings") if getattr(self, "pages", None) else None
        if settings is not None:
            try:
                settings.refresh_hotkey_summary()
            except Exception:
                pass

    def _on_hotkey_trigger(self, hotkey_id: int) -> None:
        if self._closed or self.hotkey_registry is None:
            return
        if self.grab_current() is not None:
            return
        action_id = self.hotkey_registry.action_for_id(hotkey_id)
        if not action_id:
            return
        now = time.monotonic()
        if now - self._last_hotkey_trigger.get(action_id, 0.0) < 0.45:
            return
        self._last_hotkey_trigger[action_id] = now
        page = self.pages.get("shot")
        if page is not None:
            page.start_action(action_id)

    def apply_hotkey(
        self,
        action_id: str,
        modifiers: int,
        vk: int,
        enabled: bool = True,
        replace: bool = False,
    ) -> ApplyResult:
        if self.hotkey_registry is None:
            return ApplyResult(False, "全局热键不可用：系统托盘未启动")
        result = self.hotkey_registry.apply(
            action_id, modifiers, vk, enabled=enabled, replace=replace
        )
        if result.ok:
            try:
                self.config.set_capture_hotkeys(self.hotkey_registry.config())
            except Exception as exc:  # noqa: BLE001
                hotkey_log(f"保存快捷键配置失败：{exc}")
                self.status.set_message(f"快捷键已生效，但保存失败：{exc}", "warn")
            self._refresh_hotkey_ui()
        return result

    def set_hotkey_enabled(self, action_id: str, enabled: bool) -> ApplyResult:
        if self.hotkey_registry is None:
            return ApplyResult(False, "全局热键不可用：系统托盘未启动")
        result = (
            self.hotkey_registry.enable(action_id)
            if enabled
            else self.hotkey_registry.disable(action_id)
        )
        if result.ok:
            try:
                self.config.set_capture_hotkeys(self.hotkey_registry.config())
            except Exception:
                pass
            self._refresh_hotkey_ui()
        return result

    def reset_hotkey(self, action_id: str) -> ApplyResult:
        if self.hotkey_registry is None:
            return ApplyResult(False, "全局热键不可用：系统托盘未启动")
        result = self.hotkey_registry.reset(action_id)
        if result.ok:
            try:
                self.config.set_capture_hotkeys(self.hotkey_registry.config())
            except Exception:
                pass
            self._refresh_hotkey_ui()
        return result

    def retry_hotkeys(self) -> list:
        if self.hotkey_registry is None:
            return []
        failures = self.hotkey_registry.start()
        self._refresh_hotkey_ui()
        return failures

    def export_hotkeys(self) -> str | None:
        if self.hotkey_registry is None:
            return None
        path = filedialog.asksaveasfilename(
            parent=self,
            title="导出快捷键配置",
            defaultextension=".json",
            filetypes=[("JSON 配置", "*.json")],
            initialfile="截图快捷键.json",
        )
        if not path:
            return None
        try:
            Path(path).write_text(
                json.dumps(
                    self.hotkey_registry.config(),
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001
            self.status.set_message(f"导出失败：{exc}", "error")
            return None
        return path

    def import_hotkeys(self) -> tuple[bool, str]:
        """导入并逐条校验/注册；冲突项单独处理（R-8.3）。"""
        if self.hotkey_registry is None:
            return False, "全局热键不可用"
        path = filedialog.askopenfilename(
            parent=self,
            title="导入快捷键配置",
            filetypes=[("JSON 配置", "*.json"), ("所有文件", "*.*")],
        )
        if not path:
            return False, "已取消导入"
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            return False, f"无法读取配置：{exc}"

        normalized, warnings = normalize_config(
            raw if isinstance(raw, dict) else {"items": raw},
            resolve_conflicts=False,
        )
        applied = 0
        failures: list[str] = []
        conflicts: list[dict] = []
        unresolved = 0
        for item in normalized.get("items", []):
            action_id = item["action"]
            action = ACTION_BY_ID.get(action_id)
            if action is None:
                continue
            result = self.hotkey_registry.apply(
                action_id,
                item["modifiers"],
                item["vk"],
                enabled=bool(item["enabled"]),
            )
            if result.ok:
                applied += 1
            elif result.conflict_action:
                conflicts.append(item)
            else:
                failures.append(f"{action.label}：{result.error}")

        if conflicts:
            names = "、".join(
                ACTION_BY_ID[item["action"]].label for item in conflicts
            )
            replace = messagebox.askyesno(
                "导入快捷键",
                f"以下快捷键与现有功能冲突：{names}。\n\n是否替换现有绑定？",
                parent=self,
            )
            if replace:
                for item in conflicts:
                    result = self.hotkey_registry.apply(
                        item["action"],
                        item["modifiers"],
                        item["vk"],
                        enabled=bool(item["enabled"]),
                        replace=True,
                    )
                    if result.ok:
                        applied += 1
                    else:
                        failures.append(
                            f"{ACTION_BY_ID[item['action']].label}：{result.error}"
                        )
            else:
                unresolved = len(conflicts)

        try:
            self.config.set_capture_hotkeys(self.hotkey_registry.config())
        except Exception:
            pass
        self._refresh_hotkey_ui()

        parts = [f"已应用 {applied} 项"]
        if conflicts:
            parts.append(f"{len(conflicts)} 项冲突")
        if unresolved:
            parts.append(f"{unresolved} 项冲突未替换")
        if warnings:
            parts.append(f"{len(warnings)} 条配置警告")
        if failures:
            parts.append("失败：" + "；".join(failures[:3]))
        return (not failures and not unresolved), "，".join(parts)

    def _open_screenshot(self) -> None:
        page = self.pages.get("shot")
        if page is not None:
            page.start_action("capture.region")

    def _sync_autostart(self) -> None:
        """让注册表里的自启项与设置保持一致（挪动程序目录后自动修正）。"""
        try:
            from .. import autostart

            autostart.sync(bool(self.config.settings.auto_start))
        except Exception:
            pass

    def _prune_shutdown_plan(self) -> None:
        """重启过或时间已过的关机计划直接清掉。"""
        try:
            from .. import shutdown as shutdown_mod

            plan = self.config.shutdown_plan
            if plan and not shutdown_mod.plan_is_alive(plan):
                self.config.clear_shutdown()
        except Exception:
            pass

    def shutdown_active(self) -> bool:
        try:
            from .. import shutdown as shutdown_mod

            return shutdown_mod.plan_is_alive(self.config.shutdown_plan)
        except Exception:
            return False

    def cancel_shutdown(self) -> None:
        from .. import shutdown as shutdown_mod

        ok, error = shutdown_mod.cancel()
        self.config.clear_shutdown()
        page = self.pages.get("shutdown")
        if page is not None:
            try:
                page._refresh_status()
            except Exception:
                pass
        if ok:
            self.status.set_message("已取消关机计划", "ok")
        else:
            self.status.set_message(f"取消关机可能失败：{error}", "error")

    def _update_tray_tooltip(self) -> None:
        if self.tray is None:
            return
        if self.auto_paused:
            self.tray.set_tooltip(f"{APP_TITLE} · 自动备份已暂停")
        elif self.runner.is_busy():
            self.tray.set_tooltip(f"{APP_TITLE} · 正在备份")
        else:
            self.tray.set_tooltip(f"{APP_TITLE} · 空闲")

    def is_visible(self) -> bool:
        try:
            return not self._hidden and self.state() == "normal"
        except tk.TclError:
            return False

    def show_window(self) -> None:
        if self._closed:
            return
        self._hidden = False
        try:
            self.deiconify()
            self.state("normal")
            self.lift()
            self.focus_force()
        except tk.TclError:
            pass

    def hide_window(self) -> None:
        if self._closed:
            return
        self._hidden = True
        self._close_tray_menu()
        try:
            self.withdraw()
        except tk.TclError:
            pass

    def toggle_window(self) -> None:
        if self.is_visible():
            self.hide_window()
        else:
            self.show_window()

    def _capture_menu_children(self) -> list:
        children: list = []
        registry = self.hotkey_registry
        for action in ACTIONS:
            if registry is not None:
                binding = registry.binding(action.id)
                state = registry.state(action.id)
                text = binding.text or "未设置"
                if state.status == STATUS_FAILED:
                    text += "（不可用）"
                elif not binding.enabled:
                    text += "（已禁用）"
            else:
                text = "热键不可用"
            children.append(
                (
                    f"{action.label}　{text}",
                    lambda action_id=action.id: self._tray_capture(action_id),
                )
            )
        children.append(None)
        children.append(("快捷键设置…", self._open_shot_settings))
        return children

    def _tray_capture(self, action_id: str) -> None:
        page = self.pages.get("shot")
        if page is not None:
            page.start_action(action_id)

    def _open_shot_settings(self) -> None:
        self.show_window()
        self.show_page("shot")
        page = self.pages.get("shot")
        if page is not None:
            self.after(120, page.refresh_hotkeys)

    def _show_tray_menu(self) -> None:
        if self._tray_menu is not None:
            self._close_tray_menu()
            return
        try:
            x, y = self.winfo_pointerxy()
        except tk.TclError:
            return

        menu = tk.Toplevel(self)
        menu.overrideredirect(True)
        menu.configure(bg=C.BORDER)
        try:
            menu.attributes("-topmost", True)
        except tk.TclError:
            pass
        self._tray_menu = menu

        holder = tk.Frame(menu, bg=C.CARD)
        holder.pack(fill="both", expand=True, padx=1, pady=1)

        width = sp(212)
        title = label(holder, APP_TITLE, 9, C.TEXT_MUTED, "bold", bg=C.CARD)
        title.configure(padx=sp(14), pady=sp(8))
        title.pack(fill="x")

        self._menu_separator(holder)
        self._menu_item(
            holder,
            "定时关机",
            children=[
                ("明天 08:00 关机", lambda: self._quick_shutdown("tomorrow8")),
                ("今天 08:00 关机", lambda: self._quick_shutdown("today8")),
                ("10 小时后关机", lambda: self._quick_shutdown("hours10")),
                None,
                ("自定义关机…", self._open_shutdown_page),
            ],
        )
        self._menu_item(
            holder,
            "时间闹钟",
            children=[
                ("15 分钟后提醒", lambda: self._quick_alarm(15)),
                ("60 分钟后提醒", lambda: self._quick_alarm(60)),
                None,
                ("自定义提醒…", self._open_alarm_page),
            ],
        )
        self._menu_item(
            holder,
            "截图",
            children=self._capture_menu_children(),
        )
        self._menu_item(holder, "打开备份目录", self._tray_open_root)
        self._menu_separator(holder)
        self._menu_item(holder, "退出电脑百宝箱", self.quit_app, danger=True)

        menu.update_idletasks()
        height = menu.winfo_reqheight()
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        x = max(sp(4), min(int(x) - width // 2, screen_w - width - sp(8)))
        y = max(sp(4), min(int(y) - height - sp(12), screen_h - height - sp(8)))
        menu.geometry(f"{width}x{height}+{x}+{y}")
        menu.lift()
        try:
            menu.focus_force()
        except tk.TclError:
            pass
        menu.bind("<FocusOut>", self._on_tray_menu_focus_out)
        menu.bind("<Escape>", lambda _e: self._close_tray_menu())

    def _pointer_in_tray_menu(self) -> bool:
        try:
            x, y = self.winfo_pointerxy()
        except tk.TclError:
            return False
        for widget in (self._tray_menu, self._submenu):
            if widget is None:
                continue
            try:
                left = widget.winfo_rootx()
                top = widget.winfo_rooty()
                right = left + widget.winfo_width()
                bottom = top + widget.winfo_height()
            except tk.TclError:
                continue
            if left <= x < right and top <= y < bottom:
                return True
        return False

    def _on_tray_menu_focus_out(self, _event=None) -> None:
        """子菜单是独立 Toplevel，点击它会让主菜单短暂失焦，不能立刻关闭。"""
        if self._tray_menu is None:
            return
        if self._pointer_in_tray_menu():
            return
        if self._tray_focus_job is not None:
            try:
                self.after_cancel(self._tray_focus_job)
            except Exception:
                pass
        self._tray_focus_job = self.after(180, self._close_tray_if_pointer_outside)

    def _close_tray_if_pointer_outside(self) -> None:
        self._tray_focus_job = None
        if self._tray_menu is None:
            return
        if self._pointer_in_tray_menu():
            return
        self._close_tray_menu()

    def _menu_separator(self, parent) -> None:
        line = tk.Frame(parent, bg=C.BORDER_SOFT, height=1)
        line.pack(fill="x", padx=sp(8), pady=sp(4))

    def _menu_item(
        self,
        parent,
        text: str,
        command=None,
        danger: bool = False,
        children: list | None = None,
    ):
        row = tk.Label(
            parent,
            text=f"{text}    ▸" if children else text,
            anchor="w",
            bg=C.CARD,
            fg=C.RED if danger else C.TEXT,
            font=font(10),
            padx=sp(16),
            pady=sp(7),
            cursor="hand2",
        )
        row.pack(fill="x", padx=1)
        hover = "#3A2126" if danger else C.CARD_HOVER
        if children:
            row.bind("<Enter>", lambda _e: (row.configure(bg=hover), self._open_submenu(row, children)))
        else:
            row.bind("<Enter>", lambda _e: (row.configure(bg=hover), self._schedule_submenu_close()))
        row.bind("<Leave>", lambda _e: self._schedule_submenu_close(scope=row, restore=True))
        if children:
            row.bind("<Button-1>", lambda _e: self._open_submenu(row, children))
        elif command is not None:
            row.bind("<Button-1>", lambda _e: self._invoke_menu(command))
        return row

    # ------------------------------------------------------------ 二级菜单
    def _open_submenu(self, row, children: list) -> None:
        if self._submenu_owner is row and self._submenu is not None:
            return
        self._close_submenu()
        self._cancel_submenu_close()
        if not children or not row.winfo_exists():
            return

        panel = tk.Toplevel(self)
        panel.overrideredirect(True)
        panel.configure(bg=C.BORDER)
        try:
            panel.attributes("-topmost", True)
        except tk.TclError:
            pass
        holder = tk.Frame(panel, bg=C.CARD)
        holder.pack(fill="both", expand=True, padx=1, pady=1)
        for item in children:
            if item is None:
                self._menu_separator(holder)
                continue
            text, command = item
            child = tk.Label(
                holder,
                text=text,
                anchor="w",
                bg=C.CARD,
                fg=C.TEXT,
                font=font(10),
                padx=sp(18),
                pady=sp(7),
                cursor="hand2",
            )
            child.pack(fill="x", padx=1)
            child.bind("<Enter>", lambda _e, c=child: c.configure(bg=C.CARD_HOVER))
            child.bind("<Leave>", lambda _e, c=child: c.configure(bg=C.CARD))
            child.bind("<Button-1>", lambda _e, cmd=command: self._invoke_menu(cmd))
        panel.bind("<Enter>", lambda _e: self._cancel_submenu_close())
        panel.bind("<Leave>", lambda _e: self._schedule_submenu_close())

        panel.update_idletasks()
        width = max(sp(190), panel.winfo_reqwidth())
        height = panel.winfo_reqheight()
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        x = row.winfo_rootx() + row.winfo_width() - sp(4)
        y = row.winfo_rooty() - sp(6)
        if x + width > screen_w - sp(8):
            x = max(sp(4), row.winfo_rootx() - width + sp(4))
        y = max(sp(4), min(y, screen_h - height - sp(8)))
        panel.geometry(f"{width}x{height}+{x}+{y}")
        panel.lift()

        self._submenu = panel
        self._submenu_owner = row

    def _cancel_submenu_close(self) -> None:
        if self._submenu_close is not None:
            try:
                self.after_cancel(self._submenu_close)
            except Exception:
                pass
            self._submenu_close = None

    def _schedule_submenu_close(self, scope=None, restore: bool = False) -> None:
        if restore and scope is not None:
            try:
                scope.configure(bg=C.CARD)
            except tk.TclError:
                pass
        self._cancel_submenu_close()
        self._submenu_close = self.after(280, self._close_submenu)

    def _close_submenu(self) -> None:
        self._cancel_submenu_close()
        panel = self._submenu
        self._submenu = None
        self._submenu_owner = None
        if panel is not None:
            try:
                panel.destroy()
            except tk.TclError:
                pass

    def _invoke_menu(self, command) -> None:
        self._close_submenu()
        self._close_tray_menu()
        try:
            command()
        except Exception as exc:  # noqa: BLE001
            self.status.set_message(f"操作失败：{exc}", "error")

    def _close_tray_menu(self) -> None:
        if self._tray_focus_job is not None:
            try:
                self.after_cancel(self._tray_focus_job)
            except Exception:
                pass
            self._tray_focus_job = None
        self._close_submenu()
        menu = self._tray_menu
        self._tray_menu = None
        if menu is not None:
            try:
                menu.destroy()
            except tk.TclError:
                pass

    # ------------------------------------------------------------ 快捷动作
    def _quick_shutdown(self, source: str) -> None:
        page = self.pages.get("shutdown")
        if page is None:
            return
        try:
            page.quick(source, confirm=True)
        except Exception as exc:  # noqa: BLE001
            self.status.set_message(f"设定关机失败：{exc}", "error")

    def _quick_alarm(self, minutes: int) -> None:
        page = self.pages.get("alarm")
        if page is None:
            return
        try:
            page.quick_minutes(minutes)
        except Exception as exc:  # noqa: BLE001
            self.status.set_message(f"设定提醒失败：{exc}", "error")

    def _toggle_pause(self) -> None:
        self.auto_paused = not self.auto_paused
        self._update_tray_tooltip()
        if self.auto_paused:
            self.pill.set("已暂停自动备份", C.AMBER)
            self.status.set_message("自动备份已暂停（手动备份不受影响）", "warn")
        else:
            self.pill.set("空闲", C.TEXT_MUTED)
            self.status.set_message("自动备份已恢复", "ok")

    def _open_shutdown_page(self) -> None:
        self.show_window()
        self.show_page("shutdown")

    def _open_alarm_page(self) -> None:
        self.show_window()
        self.show_page("alarm")

    def alarm_active(self) -> bool:
        try:
            from .. import alarm as alarm_mod

            return alarm_mod.is_active(self.config.alarm)
        except Exception:
            return False

    def cancel_alarm(self) -> None:
        self.config.clear_alarm()
        page = self.pages.get("alarm")
        if page is not None:
            try:
                page._refresh_status()
            except Exception:
                pass
        self.status.set_message("已取消时间提醒", "ok")

    def _tray_open_root(self) -> None:
        from ..fsutil import open_folder

        root = self.config.settings.backup_root
        if not root:
            if self.tray is not None:
                self.tray.notify("未设置备份目录", "请打开主窗口，在「设置」中指定备份根目录。")
            return
        try:
            Path(root).mkdir(parents=True, exist_ok=True)
            open_folder(root)
        except OSError as exc:
            if self.tray is not None:
                self.tray.notify("无法打开目录", str(exc))

    # ------------------------------------------------------------ 关闭
    def _on_close(self) -> None:
        if self._closed:
            return
        if self.tray is not None and self.config.settings.close_to_tray:
            self.hide_window()
            if not self._tray_hint_shown:
                self._tray_hint_shown = True
                self.tray.notify(
                    "电脑百宝箱仍在后台运行",
                    "定时备份继续生效。若任务栏看不到图标，请点右下角的「^」展开折叠区。",
                )
            return
        self.quit_app()

    def quit_app(self) -> None:
        if self._closed:
            return

        # 有关机计划时只提示状态；继续退出不会取消或修改计划。
        plan_active = self.shutdown_active()
        if plan_active:
            from .shutdown import ask_exit_with_shutdown

            choice = ask_exit_with_shutdown(self)
            if choice == "abort":
                self.status.set_message("已取消退出", "warn")
                return

        # 有关机计划时，正在备份属于“暂时无法退出”，与设置里的确认开关互不影响。
        if self.runner.is_busy():
            if plan_active:
                messagebox.showwarning(
                    "无法退出",
                    "备份任务正在进行，暂时无法关闭软件。\n\n"
                    "请等待当前备份完成后再退出；关机计划不会被修改。",
                    parent=self,
                )
                self.status.set_message("备份进行中，已取消退出", "warn")
                return
            if self.config.settings.confirm_close and self.is_visible():
                if not messagebox.askyesno(
                    "退出电脑百宝箱", "备份仍在进行，确定要退出吗？", parent=self
                ):
                    return
        self._closed = True
        self._close_tray_menu()
        if self.hotkey_registry is not None:
            try:
                self.hotkey_registry.stop()
            except Exception:
                pass
        if self.tray is not None:
            try:
                self.tray.stop()
            except Exception:
                pass
        try:
            self.runner.cancel()
        except Exception:
            pass
        try:
            self.scheduler.stop()
        except Exception:
            pass
        try:
            self.config.save()
        except Exception:
            pass
        try:
            self.destroy()
        except tk.TclError:
            pass
