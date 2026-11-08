"""设置页。"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

from .. import paths
from ..fsutil import open_folder
from ..hotkeys import ACTIONS, STATUS_ACTIVE, STATUS_FAILED, is_admin
from ..inpututils import InputError, parse_int
from ..theme import C, font, sp
from ..widgets import (
    Card,
    FlatButton,
    Input,
    ScrollFrame,
    TextArea,
    form_row,
    label,
    spinbox,
)
from .base import Page


class SettingsPage(Page):
    title = "设置"
    subtitle = "备份位置、默认排除规则与通用选项"

    def _build(self) -> None:
        scroll = ScrollFrame(self, bg=C.BG)
        scroll.pack(fill="both", expand=True)

        wrap = tk.Frame(scroll.body, bg=C.BG)
        wrap.pack(fill="both", expand=True, padx=sp(26), pady=(sp(2), sp(26)))

        settings = self.cfg.settings
        self.root_var = tk.StringVar(value=settings.backup_root)
        self.keep_var = tk.StringVar(value=str(settings.keep_versions))
        self.extraneous_var = tk.BooleanVar(value=settings.delete_extraneous)
        self.notify_var = tk.BooleanVar(value=settings.notify)
        self.close_var = tk.BooleanVar(value=settings.confirm_close)
        self.tray_close_var = tk.BooleanVar(value=settings.close_to_tray)
        self.tray_start_var = tk.BooleanVar(value=settings.start_minimized)
        self.tray_notify_var = tk.BooleanVar(value=settings.tray_notify)
        self.auto_start_var = tk.BooleanVar(value=settings.auto_start)

        # ---------------- 备份位置
        card = Card(wrap)
        card.pack(fill="x", pady=(0, sp(14)))
        label(card.body, "备份位置", 11, C.TEXT, "bold", bg=C.CARD).pack(
            anchor="w", pady=(0, sp(14))
        )

        holder = form_row(
            card.body,
            "主备份文件夹",
            "所有任务都放在这个文件夹下，按任务名建立子文件夹",
        )
        row = tk.Frame(holder, bg=C.CARD)
        row.pack(fill="x")
        Input(row, self.root_var).pack(side="left", fill="x", expand=True)
        FlatButton(
            row, "浏览…", command=self._pick_root, kind="secondary", padx=12, pady=7, font_size=9
        ).pack(side="left", padx=(sp(8), 0))
        FlatButton(
            row, "打开", command=self._open_root, kind="secondary", padx=12, pady=7, font_size=9
        ).pack(side="left", padx=(sp(8), 0))
        FlatButton(
            holder,
            "恢复默认位置（最后一个盘符）",
            command=self._default_root,
            kind="subtle",
            padx=8,
            pady=3,
            font_size=8,
            bold=False,
        ).pack(anchor="w", pady=(sp(6), 0))

        # ---------------- 默认规则
        card = Card(wrap)
        card.pack(fill="x", pady=(0, sp(14)))
        label(card.body, "默认规则", 11, C.TEXT, "bold", bg=C.CARD).pack(
            anchor="w", pady=(0, sp(14))
        )

        holder = form_row(card.body, "默认排除规则", "每行一个，新建任务时自动带入")
        self.excludes_area = TextArea(holder, height=7)
        self.excludes_area.pack(fill="x")
        self.excludes_area.set("\n".join(settings.excludes))

        holder = form_row(card.body, "新任务默认保留快照数", "0 表示不自动清理")
        self.keep_spin = spinbox(holder, from_=0, to=100, textvariable=self.keep_var, width=6)
        self.keep_spin.pack(anchor="w")

        holder = form_row(card.body, "镜像备份", "")
        self.extraneous_check = self._check(
            holder, "镜像备份时删除目标中源目录已不存在的文件", self.extraneous_var
        )
        self.extraneous_check.pack(anchor="w")

        # ---------------- 通用
        card = Card(wrap)
        card.pack(fill="x", pady=(0, sp(14)))
        label(card.body, "通用", 11, C.TEXT, "bold", bg=C.CARD).pack(
            anchor="w", pady=(0, sp(14))
        )
        self.notify_check = self._check(card.body, "备份出现问题时弹出提示", self.notify_var)
        self.notify_check.pack(anchor="w", pady=(0, sp(8)))
        self.close_check = self._check(card.body, "退出时若正在备份，先确认", self.close_var)
        self.close_check.pack(anchor="w", pady=(0, sp(12)))

        label(
            card.body,
            "新任务提交时可以选择「按计划时间」或「5 分钟后先备份一次」；"
            "错过的旧计划不会自动补跑。",
            8,
            C.TEXT_MUTED,
            bg=C.CARD,
            wraplength=sp(780),
            justify="left",
        ).pack(anchor="w", pady=(0, sp(8)))

        # ---------------- 截图快捷键
        card = Card(wrap)
        card.pack(fill="x", pady=(0, sp(14)))
        label(card.body, "截图快捷键", 11, C.TEXT, "bold", bg=C.CARD).pack(
            anchor="w", pady=(0, sp(12))
        )
        self.hotkey_rows: dict[str, tuple] = {}
        for action in ACTIONS:
            row = tk.Frame(card.body, bg=C.CARD)
            row.pack(fill="x", pady=(0, sp(6)))
            label(row, action.label, 9, C.TEXT, bg=C.CARD).pack(side="left")
            binding = label(row, "", 9, C.ACCENT, "bold", bg=C.CARD)
            binding.pack(side="left", padx=(sp(12), sp(10)))
            status = label(row, "", 8, C.TEXT_MUTED, bg=C.CARD)
            status.pack(side="left")
            self.hotkey_rows[action.id] = (binding, status)
        FlatButton(
            card.body,
            "前往「快速截图」设置快捷键",
            command=lambda: self.app.show_page("shot"),
            kind="secondary",
            font_size=9,
        ).pack(anchor="w", pady=(sp(8), 0))
        label(
            card.body,
            "注册失败的项会在这里标红；托盘菜单和快速截图页的按钮仍然可以截图。",
            8,
            C.TEXT_MUTED,
            bg=C.CARD,
        ).pack(anchor="w", pady=(sp(8), 0))
        if not is_admin():
            label(
                card.body,
                "提示：当前以普通权限运行，对管理员窗口的全局热键可能无效。",
                8,
                C.AMBER,
                bg=C.CARD,
            ).pack(anchor="w", pady=(sp(4), 0))

        # ---------------- 托盘与后台
        card = Card(wrap)
        card.pack(fill="x", pady=(0, sp(14)))
        label(card.body, "托盘与后台运行", 11, C.TEXT, "bold", bg=C.CARD).pack(
            anchor="w", pady=(0, sp(14))
        )
        self._check(
            card.body, "开机时自动启动电脑百宝箱（直接最小化到托盘）", self.auto_start_var
        ).pack(anchor="w", pady=(0, sp(4)))
        self.autostart_status = label(card.body, "", 8, C.TEXT_MUTED, bg=C.CARD)
        self.autostart_status.pack(anchor="w", pady=(0, sp(10)))
        self._check(
            card.body, "关闭窗口时最小化到系统托盘（后台继续定时备份）", self.tray_close_var
        ).pack(anchor="w", pady=(0, sp(8)))
        self._check(card.body, "启动时只显示托盘图标，不弹出主窗口", self.tray_start_var).pack(
            anchor="w", pady=(0, sp(8))
        )
        self._check(
            card.body, "窗口最小化时，用托盘气泡提示备份结果", self.tray_notify_var
        ).pack(anchor="w", pady=(0, sp(8)))
        label(
            card.body,
            "提示：右键托盘图标可以打开菜单（打开窗口 / 立即备份 / 暂停自动备份 / 退出）",
            8,
            C.TEXT_MUTED,
            bg=C.CARD,
        ).pack(anchor="w")

        # ---------------- 数据
        card = Card(wrap)
        card.pack(fill="x", pady=(0, sp(14)))
        label(card.body, "数据与关于", 11, C.TEXT, "bold", bg=C.CARD).pack(
            anchor="w", pady=(0, sp(14))
        )
        data_dir = str(paths.data_dir())
        label(card.body, "配置文件目录", 9, C.TEXT_DIM, bg=C.CARD).pack(anchor="w")
        path_row = tk.Frame(card.body, bg=C.CARD)
        path_row.pack(fill="x", pady=(sp(4), sp(12)))
        self.data_label = label(path_row, data_dir, 9, C.TEXT, bg=C.CARD)
        self.data_label.pack(side="left")
        FlatButton(
            path_row,
            "打开目录",
            command=self._open_data,
            kind="subtle",
            padx=10,
            pady=4,
            font_size=8,
            bold=False,
        ).pack(side="left", padx=(sp(12), 0))
        label(
            card.body,
            "配置随软件目录一起保存：重装系统后把整个文件夹拷回去即可继续使用。",
            8,
            C.TEXT_MUTED,
            bg=C.CARD,
        ).pack(anchor="w", pady=(0, sp(10)))

        label(
            card.body,
            f"{paths.APP_TITLE} v{paths.APP_VERSION} · 本地运行的 Windows 备份 / 关机 / 闹钟 / 计时器 / 截图工具箱",
            8,
            C.TEXT_MUTED,
            bg=C.CARD,
        ).pack(anchor="w")

        # ---------------- 保存
        actions = tk.Frame(wrap, bg=C.BG)
        actions.pack(fill="x", pady=(sp(4), 0))
        FlatButton(actions, "保存设置", command=self._save, padx=22).pack(side="right")
        FlatButton(
            actions, "恢复默认", command=self._reset, kind="ghost", padx=14
        ).pack(side="right", padx=(0, sp(10)))

        self.status = label(actions, "", 9, C.GREEN, bg=C.BG)
        self.status.pack(side="left")

    def _check(self, master, text: str, variable: tk.BooleanVar):
        return tk.Checkbutton(
            master,
            text=text,
            variable=variable,
            bg=C.CARD,
            fg=C.TEXT,
            activebackground=C.CARD,
            activeforeground=C.TEXT,
            selectcolor=C.BG_DEEP,
            highlightthickness=0,
            bd=0,
            anchor="w",
            font=font(9),
            cursor="hand2",
        )

    # ------------------------------------------------------------ 动作
    def _pick_root(self) -> None:
        path = filedialog.askdirectory(
            parent=self.app,
            title="选择备份根目录",
            initialdir=self.root_var.get() or str(Path.home()),
        )
        if path:
            self.root_var.set(str(Path(path)))

    def _open_root(self) -> None:
        target = self.root_var.get().strip()
        if not target:
            messagebox.showinfo("未设置", "请先指定备份根目录。", parent=self.app)
            return
        try:
            Path(target).mkdir(parents=True, exist_ok=True)
            open_folder(target)
        except OSError as exc:
            messagebox.showerror("无法打开", str(exc), parent=self.app)

    def _open_data(self) -> None:
        try:
            open_folder(paths.data_dir())
        except OSError as exc:
            messagebox.showerror("无法打开", str(exc), parent=self.app)

    def _default_root(self) -> None:
        self.root_var.set(paths.default_backup_root())
        self.status.configure(text="已填入默认位置，记得点击保存", fg=C.AMBER)

    def _reset(self) -> None:
        from ..config import DEFAULT_EXCLUDES, Settings

        defaults = Settings()
        self.root_var.set(defaults.backup_root)
        self.keep_var.set(str(defaults.keep_versions))
        self.extraneous_var.set(defaults.delete_extraneous)
        self.notify_var.set(defaults.notify)
        self.close_var.set(defaults.confirm_close)
        self.tray_close_var.set(defaults.close_to_tray)
        self.tray_start_var.set(defaults.start_minimized)
        self.tray_notify_var.set(defaults.tray_notify)
        self.auto_start_var.set(defaults.auto_start)
        self.excludes_area.set("\n".join(DEFAULT_EXCLUDES))
        self.status.configure(text="已恢复默认值，记得点击保存", fg=C.AMBER)

    def _save(self) -> None:
        settings = self.cfg.settings
        root = self.root_var.get().strip()
        if root:
            try:
                Path(root).mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                messagebox.showwarning("目录不可用", f"{root}\n\n{exc}", parent=self.app)
                return
        try:
            keep = parse_int(self.keep_var.get(), "新任务默认保留快照数", 0, 500)
        except InputError as exc:
            messagebox.showwarning("输入无效", str(exc), parent=self.app)
            return

        settings.backup_root = root
        settings.excludes = [
            line.strip() for line in self.excludes_area.get().splitlines() if line.strip()
        ]
        settings.keep_versions = keep
        settings.delete_extraneous = bool(self.extraneous_var.get())
        settings.notify = bool(self.notify_var.get())
        settings.confirm_close = bool(self.close_var.get())
        settings.close_to_tray = bool(self.tray_close_var.get())
        settings.start_minimized = bool(self.tray_start_var.get())
        settings.tray_notify = bool(self.tray_notify_var.get())
        settings.auto_start = bool(self.auto_start_var.get())
        if not self.cfg.save():
            messagebox.showerror(
                "保存失败",
                f"无法写入配置文件：\n{self.cfg.last_save_error or self.cfg.path}",
                parent=self.app,
            )
            self.status.configure(text="保存失败", fg=C.RED)
            return

        from .. import autostart

        if not autostart.sync(settings.auto_start):
            messagebox.showwarning(
                "开机自启设置失败",
                "无法写入注册表启动项。\n"
                "如果程序在受保护目录下，请改用便携路径，或手动创建快捷方式。",
                parent=self.app,
            )
        self._update_autostart_status()
        self.app._refresh_sidebar()
        self.status.configure(text="设置已保存", fg=C.GREEN)
        self.app.status.set_message("设置已保存", "ok")

    def _update_autostart_status(self) -> None:
        if not hasattr(self, "autostart_status"):
            return
        try:
            from .. import autostart

            command = autostart.current_command()
            if command:
                text = f"已登记启动项：{command}"
                if len(text) > 90:
                    text = text[:87] + "…"
            else:
                text = "当前没有登记启动项"
        except Exception:
            text = ""
        try:
            self.autostart_status.configure(text=text)
        except tk.TclError:
            pass

    def refresh_hotkey_summary(self) -> None:
        registry = getattr(self.app, "hotkey_registry", None)
        for action in ACTIONS:
            row = self.hotkey_rows.get(action.id)
            if not row:
                continue
            binding_label, status_label = row
            if registry is None:
                binding_label.configure(text="—")
                status_label.configure(text="热键不可用", fg=C.RED)
                continue
            binding = registry.binding(action.id)
            state = registry.state(action.id)
            binding_label.configure(text=binding.text or "未设置")
            if state.status == STATUS_ACTIVE:
                if state.error:
                    status_label.configure(text="仍用旧键（新键失败）", fg=C.AMBER)
                else:
                    status_label.configure(text="已注册", fg=C.GREEN)
            elif state.status == STATUS_FAILED:
                status_label.configure(text="注册失败：可能被占用", fg=C.RED)
            elif binding.enabled:
                status_label.configure(text="未设置", fg=C.TEXT_DIM)
            else:
                status_label.configure(text="已禁用", fg=C.TEXT_MUTED)

    def refresh(self) -> None:
        settings = self.cfg.settings
        self.root_var.set(settings.backup_root)
        self.keep_var.set(str(settings.keep_versions))
        self.extraneous_var.set(settings.delete_extraneous)
        self.notify_var.set(settings.notify)
        self.close_var.set(settings.confirm_close)
        self.tray_close_var.set(settings.close_to_tray)
        self.tray_start_var.set(settings.start_minimized)
        self.tray_notify_var.set(settings.tray_notify)
        self.auto_start_var.set(settings.auto_start)
        self.excludes_area.set("\n".join(settings.excludes))
        self._update_autostart_status()
        self.refresh_hotkey_summary()
        self.status.configure(text="")
