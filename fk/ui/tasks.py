"""备份任务页与任务编辑对话框。"""
from __future__ import annotations

import os
import threading
import tkinter as tk
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ..backup import (
    list_snapshots,
    normalize_exts,
    plan_restore,
    restore_snapshot,
)
from ..config import Schedule, Task, new_id
from ..fsutil import (
    human_ago,
    human_size,
    human_time,
    is_inside,
    sanitize_name,
    weekday_name,
)
from ..inpututils import InputError, parse_int
from ..theme import C, font, sp
from ..widgets import (
    Card,
    FlatButton,
    Input,
    ScrollFrame,
    Segmented,
    StatCard,
    TextArea,
    center_over,
    fit_text,
    form_row,
    label,
    run_bg,
    spinbox,
)
from .base import Page
from .picker import pick_paths

COLUMNS = [
    ("status", "状态", 82),
    ("name", "任务名称", 140),
    ("source", "备份内容", 240),
    ("target", "备份到", 200),
    ("mode", "方式", 96),
    ("schedule", "自动备份", 108),
    ("last", "上次备份", 100),
]

STATUS_TEXT = {
    "success": "成功",
    "partial": "部分成功",
    "failed": "失败",
    "cancelled": "已取消",
}


def _elide(text: str, limit: int = 44) -> str:
    text = str(text or "")
    if len(text) <= limit:
        return text
    head = limit // 2 - 2
    tail = limit - head - 3
    return f"{text[:head]}…{text[-tail:]}"


def _checkbutton(master, text: str, variable: tk.BooleanVar, bg: str = C.CARD):
    return tk.Checkbutton(
        master,
        text=text,
        variable=variable,
        bg=bg,
        fg=C.TEXT,
        activebackground=bg,
        activeforeground=C.TEXT,
        selectcolor=C.BG_DEEP,
        highlightthickness=0,
        bd=0,
        anchor="w",
        font=font(9),
        cursor="hand2",
    )


class TasksPage(Page):
    title = "备份任务"
    subtitle = "查看备份概况、管理任务、随时立即备份"

    def _build(self) -> None:
        self._running: set[str] = set()

        # ---- 概览统计
        stats = tk.Frame(self, bg=C.BG)
        stats.pack(fill="x", padx=sp(26), pady=(0, sp(14)))
        for col in range(3):
            stats.grid_columnconfigure(col, weight=1, uniform="stat")
        self.card_tasks = StatCard(stats, "备份任务", "0", "尚未创建任务", C.ACCENT)
        self.card_tasks.grid(row=0, column=0, sticky="nsew", padx=(0, sp(12)))
        self.card_last = StatCard(stats, "上次备份", "—", "还没有备份记录", C.GREEN)
        self.card_last.grid(row=0, column=1, sticky="nsew", padx=(0, sp(12)))
        self.card_size = StatCard(stats, "备份占用", "—", "统计中…", C.AMBER)
        self.card_size.grid(row=0, column=2, sticky="nsew")

        bar = tk.Frame(self, bg=C.BG)
        bar.pack(fill="x", padx=sp(26), pady=(0, sp(14)))

        self.btn_new = FlatButton(bar, "＋ 新建任务", command=self._new_task)
        self.btn_new.pack(side="left")
        self.btn_run = FlatButton(
            bar, "立即备份", command=self._run_selected, kind="secondary", padx=13
        )
        self.btn_run.pack(side="left", padx=(sp(8), 0))
        self.btn_edit = FlatButton(
            bar, "编辑", command=self._edit_selected, kind="secondary", padx=13
        )
        self.btn_edit.pack(side="left", padx=(sp(8), 0))
        self.btn_restore = FlatButton(
            bar, "还原…", command=self._restore_selected, kind="secondary", padx=13
        )
        self.btn_restore.pack(side="left", padx=(sp(8), 0))
        self.btn_log = FlatButton(
            bar, "备份日志", command=self._open_log, kind="secondary", padx=13
        )
        self.btn_log.pack(side="left", padx=(sp(8), 0))
        self.btn_dir = FlatButton(
            bar, "打开目录", command=self._open_root, kind="secondary", padx=13
        )
        self.btn_dir.pack(side="left", padx=(sp(8), 0))
        self.btn_delete = FlatButton(
            bar, "删除", command=self._delete_selected, kind="danger", padx=13
        )
        self.btn_delete.pack(side="left", padx=(sp(8), 0))

        self.summary = label(bar, "", 9, C.TEXT_MUTED, bg=C.BG)
        self.summary.pack(side="right")

        holder = tk.Frame(
            self, bg=C.CARD, highlightbackground=C.BORDER, highlightthickness=1, bd=0
        )
        holder.pack(fill="both", expand=True, padx=sp(26), pady=(0, sp(22)))
        holder.grid_rowconfigure(0, weight=1)
        holder.grid_columnconfigure(0, weight=1)

        self.tree = ttk.Treeview(
            holder,
            columns=[c[0] for c in COLUMNS],
            show="headings",
            style="Data.Treeview",
            selectmode="browse",
        )
        for key, text, width in COLUMNS:
            self.tree.heading(key, text=text, anchor="w")
            self.tree.column(
                key,
                width=sp(width),
                minwidth=sp(60),
                anchor="w",
                stretch=(key in ("source", "target")),
            )
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(holder, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)

        self.tree.tag_configure("failed", foreground=C.RED)
        self.tree.tag_configure("running", foreground=C.ACCENT)
        self.tree.tag_configure("off", foreground=C.TEXT_MUTED)
        self.tree.tag_configure("stripe", background="#1E232D")

        self.empty = label(
            holder, "还没有备份任务，点击左上角「新建任务」开始。", 10, C.TEXT_MUTED, bg=C.CARD
        )
        self.empty.grid(row=0, column=0)

        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._sync_buttons())
        self.tree.bind("<Double-1>", lambda _e: self._edit_selected())

        self._sync_buttons()

    # ------------------------------------------------------------ 数据
    def _selected_id(self) -> str | None:
        selection = self.tree.selection()
        return selection[0] if selection else None

    def _selected_task(self) -> Task | None:
        task_id = self._selected_id()
        return self.cfg.get_task(task_id) if task_id else None

    def _sync_buttons(self) -> None:
        has = self._selected_id() is not None
        for button in (
            self.btn_run,
            self.btn_edit,
            self.btn_restore,
            self.btn_log,
            self.btn_delete,
        ):
            button.set_enabled(has)

    # ------------------------------------------------------------ 概览统计
    def _refresh_stats(self, tasks) -> None:
        enabled = sum(1 for task in tasks if task.enabled)
        if tasks:
            self.card_tasks.set(str(len(tasks)), f"{enabled} 个已启用")
        else:
            self.card_tasks.set("0", "尚未创建任务")

        runs = [task for task in tasks if task.last_run]
        if runs:
            latest = max(runs, key=lambda t: t.last_run)
            self.card_last.set(
                human_ago(latest.last_run),
                f"{latest.name} · {human_time(latest.last_run)}",
            )
        else:
            self.card_last.set("—", "还没有备份记录")

        self.app.backup_bytes(self._on_size)

    def _on_size(self, value: int) -> None:
        try:
            if value < 0:
                self.card_size.set("—", "无法统计")
            else:
                self.card_size.set(human_size(value), "所有任务目标目录累计大小")
        except tk.TclError:
            pass

    def _open_root(self) -> None:
        from ..fsutil import ensure_dir, open_folder

        root = self.cfg.settings.backup_root
        if not root:
            messagebox.showinfo(
                "未设置", "请先在「设置」中指定主备份文件夹。", parent=self.app
            )
            return
        try:
            ensure_dir(root)
            open_folder(root)
        except OSError as exc:
            messagebox.showerror("无法打开", str(exc), parent=self.app)

    def refresh(self) -> None:
        selected = self._selected_id()
        for item in self.tree.get_children():
            self.tree.delete(item)

        tasks = list(self.cfg.tasks)
        self._refresh_stats(tasks)
        for index, task in enumerate(tasks):
            if task.id in self._running:
                status = "运行中"
                tag = "running"
            elif not task.enabled:
                status = "已停用"
                tag = "off"
            elif task.last_status == "failed":
                status = "失败"
                tag = "failed"
            elif task.last_status:
                status = STATUS_TEXT.get(task.last_status, task.last_status)
                tag = ""
            else:
                status = "待运行"
                tag = ""
            tags = [tag] if tag else []
            if index % 2 == 1:
                tags.append("stripe")
            self.tree.insert(
                "",
                "end",
                iid=task.id,
                values=(
                    status,
                    task.name,
                    fit_text(self.tree, task.sources_summary(), sp(240) - sp(22)),
                    fit_text(self.tree, task.target, sp(200) - sp(22)),
                    task.mode_label,
                    task.schedule.describe(),
                    human_ago(task.last_run),
                ),
                tags=tuple(tags),
            )

        if tasks:
            total_bytes = sum(t.last_bytes for t in tasks)
            self.summary.configure(
                text=f"共 {len(tasks)} 个任务 · 最近一次共复制 {human_size(total_bytes)}"
            )
            self.empty.grid_remove()
        else:
            self.summary.configure(text="")
            self.empty.grid()

        if selected and self.tree.exists(selected):
            self.tree.selection_set(selected)
        elif tasks:
            first = tasks[0].id
            if self.tree.exists(first):
                self.tree.selection_set(first)
        self._sync_buttons()

    # ------------------------------------------------------------ 动作
    def _new_task(self) -> None:
        dialog = TaskDialog(self.app, None, self._on_saved)
        center_over(dialog, self.app)
        self.app.wait_window(dialog)

    def _edit_selected(self) -> None:
        task = self._selected_task()
        if task is None:
            return
        dialog = TaskDialog(self.app, task, self._on_saved)
        center_over(dialog, self.app)
        self.app.wait_window(dialog)

    def _on_saved(self, task: Task, is_new: bool) -> None:
        if is_new:
            self.cfg.add_task(task)
        else:
            self.cfg.update_task(task)
        if self.cfg.last_save_error:
            messagebox.showerror(
                "任务保存失败",
                f"任务已加入当前列表，但无法写入配置文件：\n{self.cfg.last_save_error}",
                parent=self.app,
            )
        self.refresh()
        self.app.refresh_all()

    def _run_selected(self) -> None:
        task = self._selected_task()
        if task is None:
            return
        self.app.backup_task(task.id)

    def _delete_selected(self) -> None:
        task = self._selected_task()
        if task is None:
            return
        if not messagebox.askyesno(
            "删除任务",
            f"确定删除任务「{task.name}」吗？\n\n已备份的文件不会被删除。",
            parent=self.app,
        ):
            return
        self.cfg.remove_task(task.id)
        if self.cfg.last_save_error:
            messagebox.showerror(
                "保存失败",
                f"任务已从当前列表移除，但配置文件写入失败：\n"
                f"{self.cfg.last_save_error}",
                parent=self.app,
            )
        self.refresh()
        self.app.refresh_all()

    def _restore_selected(self) -> None:
        task = self._selected_task()
        if task is None:
            return
        target = Path(task.target)
        if task.mode == "snapshot" or (task.mode == "pick" and task.pick_snapshot):
            snapshots = list_snapshots(task.target)
            if not snapshots:
                messagebox.showinfo("没有快照", "该任务还没有可用的时间戳快照。", parent=self.app)
                return
            if len(snapshots) == 1:
                source = snapshots[0]
            else:
                picker = PickerDialog(self.app, "选择要还原的快照", [p.name for p in snapshots])
                center_over(picker, self.app)
                self.app.wait_window(picker)
                if picker.result is None:
                    return
                source = snapshots[picker.result]
        else:
            source = target
            if not source.exists():
                messagebox.showinfo("备份不存在", f"找不到备份目录：{source}", parent=self.app)
                return

        dest = filedialog.askdirectory(parent=self.app, title="选择还原到哪个文件夹")
        if not dest:
            return
        self._prepare_restore(source, dest)

    def _open_log(self) -> None:
        task = self._selected_task()
        if task is None:
            return
        from ..audit import log_path

        path = log_path(task.target)
        if path is None or not path.exists():
            messagebox.showinfo(
                "还没有备份日志",
                f"这个任务还没有备份记录。\n\n备份成功后日志会出现在：\n{task.target}",
                parent=self.app,
            )
            return
        try:
            os.startfile(str(path))  # noqa: S606
        except OSError as exc:
            messagebox.showerror("无法打开日志", str(exc), parent=self.app)

    def _prepare_restore(self, source: Path, dest: str) -> None:
        self.app.status.indeterminate(f"正在检查还原目标 {dest} …")
        cancel = threading.Event()
        self.app.status.set_cancel_action(cancel.set)

        def work():
            return plan_restore(source, dest, cancel=cancel)

        def done(kind, value) -> None:
            self.app.status.set_cancel_action(None)
            self.app.status.idle()
            if kind == "err":
                messagebox.showerror("无法检查还原目标", str(value), parent=self.app)
                return
            plan = value
            if plan.cancelled:
                self.app.status.set_message("已取消还原检查", "warn")
                return
            if plan.errors:
                messagebox.showwarning(
                    "还原检查有问题",
                    f"有 {len(plan.errors)} 项无法读取：\n\n"
                    + "\n".join(plan.errors[:5]),
                    parent=self.app,
                )
            if plan.files <= 0:
                messagebox.showinfo("没有文件", "这个备份里没有可还原的文件。", parent=self.app)
                return
            if plan.conflicts:
                choice = messagebox.askyesnocancel(
                    "还原冲突",
                    f"共 {plan.files} 个文件，目标中已有 {plan.conflicts} 个同名文件。\n\n"
                    "是：覆盖同名文件\n"
                    "否：跳过同名文件\n"
                    "取消：不还原",
                    parent=self.app,
                )
                if choice is None:
                    return
                overwrite = bool(choice)
            else:
                if not messagebox.askyesno(
                    "确认还原",
                    f"将把 {plan.files} 个文件（{human_size(plan.total_bytes)}）"
                    f"还原到：\n{dest}\n\n继续吗？",
                    parent=self.app,
                ):
                    return
                overwrite = True
            self._do_restore(source, dest, overwrite=overwrite)

        run_bg(self.app, work, done)

    def _do_restore(self, source: Path, dest: str, overwrite: bool = True) -> None:
        self.app.status.indeterminate(f"正在还原到 {dest} …")
        cancel = threading.Event()
        self.app.status.set_cancel_action(cancel.set)

        def work():
            return restore_snapshot(source, dest, cancel=cancel, overwrite=overwrite)

        def done(kind, value) -> None:
            self.app.status.set_cancel_action(None)
            self.app.status.idle()
            if kind == "err":
                messagebox.showerror("还原失败", str(value), parent=self.app)
                return
            if value.status == "cancelled":
                self.app.status.set_message("还原已取消", "warn")
                return
            if value.errors:
                messagebox.showwarning(
                    "还原部分完成",
                    f"{value.summary}\n\n" + "\n".join(value.errors[:5]),
                    parent=self.app,
                )
            else:
                messagebox.showinfo(
                    "还原完成",
                    f"已还原 {value.copied} 个文件到：\n{dest}",
                    parent=self.app,
                )
            self.app.status.set_message(f"还原完成：{value.summary}", "ok")

        run_bg(self.app, work, done)

    # ------------------------------------------------------------ 备份事件
    def on_backup_event(self, kind: str, payload) -> None:
        if kind == "start":
            task_id = payload[0]
            self._running.add(task_id)
            if self.tree.exists(task_id):
                values = list(self.tree.item(task_id, "values"))
                values[0] = "运行中"
                self.tree.item(task_id, values=values, tags=("running",))
        elif kind == "done":
            task_id = payload[0]
            self._running.discard(task_id)
            self.refresh()


class PickerDialog(tk.Toplevel):
    """通用的单选列表对话框。"""

    def __init__(self, master, title: str, items: list[str]):
        super().__init__(master)
        self.result: int | None = None
        self.title(title)
        self.configure(bg=C.BG)
        self.geometry(f"{sp(460)}x{sp(440)}")
        self.transient(master)
        self.resizable(True, True)

        label(self, title, 11, C.TEXT, "bold", bg=C.BG).pack(
            anchor="w", padx=sp(20), pady=(sp(18), sp(10))
        )

        holder = tk.Frame(self, bg=C.CARD, highlightbackground=C.BORDER, highlightthickness=1)
        holder.pack(fill="both", expand=True, padx=sp(20))
        self.listbox = tk.Listbox(
            holder,
            bg=C.CARD,
            fg=C.TEXT,
            selectbackground=C.ACCENT_SOFT,
            selectforeground="#FFFFFF",
            relief="flat",
            bd=0,
            highlightthickness=0,
            font=font(10),
            activestyle="none",
        )
        scroll = ttk.Scrollbar(holder, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scroll.set)
        self.listbox.pack(side="left", fill="both", expand=True, padx=sp(4), pady=sp(4))
        scroll.pack(side="right", fill="y")
        for item in items:
            self.listbox.insert("end", item)
        if items:
            self.listbox.selection_set(0)

        footer = tk.Frame(self, bg=C.BG)
        footer.pack(fill="x", padx=sp(20), pady=sp(16))
        FlatButton(footer, "确定", command=self._ok).pack(side="right")
        FlatButton(footer, "取消", command=self._cancel, kind="ghost").pack(
            side="right", padx=(0, sp(8))
        )
        self.listbox.bind("<Double-1>", lambda _e: self._ok())
        self.protocol("WM_DELETE_WINDOW", self._cancel)

    def _ok(self) -> None:
        selection = self.listbox.curselection()
        self.result = int(selection[0]) if selection else None
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()


class TaskDialog(tk.Toplevel):
    """新建/编辑备份任务的模态窗口。"""

    def __init__(self, app, task: Task | None, on_save):
        super().__init__(app)
        self.app = app
        self.original = task
        self.on_save = on_save
        self.is_new = task is None

        self.title("新建备份任务" if self.is_new else "编辑备份任务")
        self.configure(bg=C.BG)
        screen_h = self.winfo_screenheight()
        width = sp(800)
        height = min(sp(920), screen_h - sp(70))
        self.geometry(f"{width}x{height}")
        self.minsize(sp(700), sp(600))
        self.transient(app)
        self._build()
        self.grab_set()
        self.bind("<Escape>", lambda _e: self.destroy())

    # ------------------------------------------------------------ 构建
    def _build(self) -> None:
        header = tk.Frame(self, bg=C.BG)
        header.pack(fill="x", padx=sp(24), pady=(sp(20), sp(12)))
        label(
            header,
            "新建备份任务" if self.is_new else "编辑备份任务",
            15,
            C.TEXT,
            "bold",
            bg=C.BG,
        ).pack(side="left")
        label(
            header,
            "可备份单个文件、多个文件夹，或按规则挑选指定类型",
            9,
            C.TEXT_MUTED,
            bg=C.BG,
        ).pack(side="left", padx=(sp(12), 0), pady=(sp(4), 0))

        footer = tk.Frame(self, bg=C.BG_DEEP)
        footer.pack(fill="x", side="bottom")
        inner = tk.Frame(footer, bg=C.BG_DEEP)
        inner.pack(fill="x", padx=sp(24), pady=sp(14))
        FlatButton(inner, "保存任务", command=self._save, padx=22).pack(side="right")
        FlatButton(inner, "取消", command=self.destroy, kind="ghost").pack(
            side="right", padx=(0, sp(10))
        )

        scroll = ScrollFrame(self, bg=C.BG)
        scroll.pack(fill="both", expand=True, padx=sp(16))
        body = tk.Frame(scroll.body, bg=C.BG)
        body.pack(fill="both", expand=True, padx=sp(8), pady=sp(4))

        task = self.original
        settings = self.app.config.settings

        self.name_var = tk.StringVar(value=task.name if task else "")
        self.target_var = tk.StringVar(value=task.target if task else "")
        self.mode_var = tk.StringVar(value=task.mode if task else "mirror")
        self.keep_var = tk.StringVar(value=str(task.keep_versions if task else settings.keep_versions))
        self.extraneous_var = tk.BooleanVar(
            value=task.delete_extraneous if task else settings.delete_extraneous
        )
        self.enabled_var = tk.BooleanVar(value=task.enabled if task else True)
        self.sched_var = tk.StringVar(value=task.schedule.type if task else "off")
        self.interval_var = tk.StringVar(value=str(task.schedule.interval_min if task else 60))
        self.time_var = tk.StringVar(value=task.schedule.time if task else "22:00")
        self.days = set(task.schedule.weekdays if task else [1, 2, 3, 4, 5])

        self.pick_exts_var = tk.StringVar(value=", ".join(task.pick_exts) if task else "")
        self.pick_rule_var = tk.StringVar(value=task.pick_rule if task else "newest")
        self.pick_count_var = tk.StringVar(value=str(task.pick_count if task else 1))
        self.pick_days_var = tk.StringVar(value=str(task.pick_days if task else 0))
        self.pick_recursive_var = tk.BooleanVar(value=task.pick_recursive if task else True)
        self.pick_snapshot_var = tk.BooleanVar(value=task.pick_snapshot if task else False)

        self.master_var = tk.StringVar(value=settings.backup_root)
        self.first_run_var = tk.StringVar(value="schedule")

        custom_target = False
        if task is not None and task.target:
            expected = Path(settings.backup_root) / sanitize_name(task.name)
            try:
                custom_target = Path(task.target).resolve() != expected.resolve()
            except OSError:
                custom_target = str(task.target) != str(expected)
        self.custom_target_var = tk.BooleanVar(value=custom_target)

        self.sources: list[str] = list(task.sources) if task else []

        # ---- 基本信息
        section = self._section(body, "基本信息")

        holder = form_row(section, "任务名称", "用于区分不同备份")
        self.name_input = Input(holder, self.name_var)
        self.name_input.pack(fill="x")

        holder = form_row(
            section,
            "备份内容",
            "单个文件夹 = 同步其内容；多个条目 = 每个文件夹放进同名子目录",
        )
        box = tk.Frame(holder, bg=C.CARD)
        box.pack(fill="x")
        self.sources_list = tk.Listbox(
            box,
            height=4,
            bg=C.CARD_ALT,
            fg=C.TEXT,
            selectbackground=C.ACCENT_SOFT,
            selectforeground="#FFFFFF",
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=C.BORDER,
            highlightcolor=C.ACCENT,
            font=font(9),
            activestyle="none",
            exportselection=False,
        )
        self.sources_list.pack(side="left", fill="both", expand=True)
        source_scroll = ttk.Scrollbar(box, orient="vertical", command=self.sources_list.yview)
        self.sources_list.configure(yscrollcommand=source_scroll.set)
        source_scroll.pack(side="right", fill="y")

        buttons = tk.Frame(holder, bg=C.CARD)
        buttons.pack(fill="x", pady=(sp(8), 0))
        for text, command in (
            ("＋ 添加文件夹", self._add_folder),
            ("＋ 添加文件", self._add_files),
            ("移除", self._remove_source),
            ("清空", self._clear_sources),
        ):
            FlatButton(
                buttons, text, command=command, kind="secondary", padx=11, pady=5, font_size=9
            ).pack(side="left", padx=(0, sp(8)))

        holder = form_row(
            section,
            "主备份文件夹",
            "所有任务都会在这个文件夹下、按任务名建立子文件夹",
        )
        master_row = tk.Frame(holder, bg=C.CARD)
        master_row.pack(fill="x")
        self.master_input = Input(master_row, self.master_var)
        self.master_input.pack(side="left", fill="x", expand=True)
        self.master_input.entry.configure(state="readonly")
        FlatButton(
            master_row,
            "更改…",
            command=self._change_master,
            kind="secondary",
            padx=12,
            pady=7,
            font_size=9,
        ).pack(side="left", padx=(sp(8), 0))

        self.preview_label = label(section, "", 9, C.ACCENT, bg=C.CARD)
        self.preview_label.pack(anchor="w", pady=(sp(2), sp(10)))

        _checkbutton(
            section, "高级：为这个任务指定别的目标目录", self.custom_target_var
        ).pack(anchor="w")

        self.custom_box = tk.Frame(section, bg=C.CARD)
        custom_row = tk.Frame(self.custom_box, bg=C.CARD)
        custom_row.pack(fill="x", pady=(sp(8), 0))
        Input(custom_row, self.target_var).pack(side="left", fill="x", expand=True)
        FlatButton(
            custom_row,
            "浏览…",
            command=self._pick_target,
            kind="secondary",
            padx=12,
            pady=7,
            font_size=9,
        ).pack(side="left", padx=(sp(8), 0))

        # ---- 备份方式
        section = self._section(body, "备份方式")
        holder = form_row(section, "方式", "")
        Segmented(
            holder,
            [
                ("mirror", "镜像同步"),
                ("snapshot", "时间戳快照"),
                ("pick", "智能挑选"),
            ],
            self.mode_var,
            bg=C.CARD,
        ).pack(anchor="w")
        self.mode_hint = label(section, "", 8, C.TEXT_MUTED, bg=C.CARD)
        self.mode_hint.pack(anchor="w", pady=(0, sp(12)))

        self.mode_box = tk.Frame(section, bg=C.CARD)
        self.mode_box.pack(fill="x")

        # ---- 排除规则
        section = self._section(body, "排除规则")
        holder = form_row(section, "排除规则", "每行一个，支持 * 通配符")
        self.excludes_area = TextArea(holder, height=4)
        self.excludes_area.pack(fill="x")
        default_excludes = task.effective_excludes(settings) if task else list(settings.excludes)
        self.excludes_area.set("\n".join(default_excludes))

        # ---- 自动备份
        section = self._section(body, "自动备份")
        holder = form_row(section, "计划", "软件运行时按计划自动备份")
        Segmented(
            holder,
            [
                ("off", "关闭"),
                ("interval", "每隔几分钟"),
                ("daily", "每天"),
                ("weekly", "每周"),
            ],
            self.sched_var,
            bg=C.CARD,
        ).pack(anchor="w")
        self.sched_box = tk.Frame(section, bg=C.CARD)
        self.sched_box.pack(fill="x", pady=(0, sp(6)))

        holder = form_row(section, "任务状态", "")
        _checkbutton(holder, "启用此任务", self.enabled_var).pack(anchor="w")

        if self.is_new:
            holder = form_row(
                section,
                "首次备份",
                "只在新任务提交后生效；之后仍按上面的计划运行",
            )
            Segmented(
                holder,
                [
                    ("schedule", "到达设定时间自动备份"),
                    ("after5", "5 分钟后先备份一次"),
                ],
                self.first_run_var,
                bg=C.CARD,
            ).pack(anchor="w")
            label(
                holder,
                "选「5 分钟后」时，任务提交后先执行一次；如果上面的计划是「关闭」，"
                "就只执行这一次，不会自动补跑错过的旧计划。",
                8,
                C.TEXT_MUTED,
                bg=C.CARD,
                wraplength=sp(600),
                justify="left",
            ).pack(anchor="w", pady=(sp(6), 0))

        self.mode_var.trace_add("write", lambda *_: self._on_mode_change())
        self.sched_var.trace_add("write", lambda *_: self._render_schedule())
        self.pick_rule_var.trace_add("write", lambda *_: self._render_mode_detail())
        self.name_var.trace_add("write", lambda *_: self._update_preview())
        self.custom_target_var.trace_add("write", lambda *_: self._on_custom_toggle())
        self.target_var.trace_add("write", lambda *_: self._update_preview())
        self._refresh_sources()
        self._on_mode_change()
        self._render_schedule()
        self._on_custom_toggle()

    def _section(self, parent, title: str) -> tk.Frame:
        card = Card(parent)
        card.pack(fill="x", pady=(0, sp(14)))
        label(card.body, title, 10, C.TEXT, "bold", bg=C.CARD).pack(
            anchor="w", pady=(0, sp(14))
        )
        return card.body

    # ------------------------------------------------------------ 来源列表
    def _refresh_sources(self) -> None:
        self.sources_list.delete(0, "end")
        for item in self.sources:
            prefix = "[文件夹] " if Path(item).is_dir() else "[文件]   "
            self.sources_list.insert("end", prefix + item)

    def _pick_paths(self, mode: str) -> list[str]:
        try:
            paths = pick_paths(self, mode=mode)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(
                "选择器错误",
                f"无法打开文件选择器：\n{exc}",
                parent=self,
            )
            paths = []
        try:
            self.grab_set()
        except tk.TclError:
            pass
        return paths

    def _add_folder(self) -> None:
        paths = self._pick_paths("folders")
        added = False
        for path in paths:
            path = str(Path(path))
            if path not in self.sources:
                self.sources.append(path)
                added = True
        if not added:
            return
        self._refresh_sources()
        if not self.name_var.get().strip():
            self.name_var.set(Path(self.sources[0]).name or "备份任务")

    def _add_files(self) -> None:
        paths = self._pick_paths("files")
        added = False
        for path in paths:
            path = str(Path(path))
            if path not in self.sources:
                self.sources.append(path)
                added = True
        if added:
            self._refresh_sources()
            if not self.name_var.get().strip():
                first = Path(self.sources[0])
                self.name_var.set(first.stem or first.name or "备份任务")

    def _remove_source(self) -> None:
        selection = self.sources_list.curselection()
        if not selection:
            return
        index = int(selection[0])
        if 0 <= index < len(self.sources):
            self.sources.pop(index)
            self._refresh_sources()

    def _clear_sources(self) -> None:
        self.sources = []
        self._refresh_sources()

    # ------------------------------------------------------------ 动态区域
    def _on_mode_change(self) -> None:
        mode = self.mode_var.get()
        hint = {
            "mirror": "目标目录始终与来源保持一致，只复制新增或修改过的文件，速度更快。",
            "snapshot": "每次备份都在目标目录下新建一个带时间戳的独立文件夹，可保留多个历史版本。",
            "pick": "在来源中找出指定类型的文件（如 .zip），按「最新 / 最大」规则只备份其中一部分。",
        }.get(mode, "")
        self.mode_hint.configure(text=hint)
        self._render_mode_detail()

    def _render_mode_detail(self) -> None:
        for child in self.mode_box.winfo_children():
            child.destroy()

        mode = self.mode_var.get()

        if mode == "mirror":
            holder = form_row(self.mode_box, "镜像清理", "删除目标中来源已不存在的文件")
            _checkbutton(
                holder, "镜像备份时删除目标中多余的文件", self.extraneous_var
            ).pack(anchor="w")
            return

        if mode == "snapshot":
            holder = form_row(self.mode_box, "保留快照数量", "0 表示不清理")
            spinbox(holder, from_=0, to=500, textvariable=self.keep_var, width=6).pack(
                anchor="w"
            )
            return

        # ---- 智能挑选
        holder = form_row(
            self.mode_box, "文件类型", "用逗号分隔，留空表示不限类型"
        )
        pick_input = Input(holder, self.pick_exts_var)
        pick_input.pack(fill="x")
        pick_input.entry.configure()

        holder = form_row(self.mode_box, "挑选规则", "")
        Segmented(
            holder,
            [("newest", "最新的"), ("largest", "最大的"), ("all", "全部")],
            self.pick_rule_var,
            bg=C.CARD,
        ).pack(anchor="w")

        count_row = tk.Frame(self.mode_box, bg=C.CARD)
        count_row.pack(fill="x", pady=(0, sp(14)))
        label(count_row, "数量", 9, C.TEXT_DIM, bg=C.CARD).pack(side="left")
        self.pick_count_spin = spinbox(
            count_row, from_=1, to=999, textvariable=self.pick_count_var, width=6
        )
        self.pick_count_spin.pack(side="left", padx=sp(10))
        label(count_row, "个（选「全部」时此值无效）", 8, C.TEXT_MUTED, bg=C.CARD).pack(
            side="left"
        )
        self.pick_count_spin.configure(
            state="disabled" if self.pick_rule_var.get() == "all" else "normal"
        )

        time_row = tk.Frame(self.mode_box, bg=C.CARD)
        time_row.pack(fill="x", pady=(0, sp(14)))
        label(time_row, "时间范围", 9, C.TEXT_DIM, bg=C.CARD).pack(side="left")
        spinbox(
            time_row, from_=0, to=3650, textvariable=self.pick_days_var, width=6
        ).pack(side="left", padx=sp(10))
        label(time_row, "天内（0 表示不限）", 8, C.TEXT_MUTED, bg=C.CARD).pack(side="left")

        check_row = tk.Frame(self.mode_box, bg=C.CARD)
        check_row.pack(fill="x", pady=(0, sp(8)))
        _checkbutton(check_row, "包含子文件夹", self.pick_recursive_var).pack(anchor="w")

        check_row = tk.Frame(self.mode_box, bg=C.CARD)
        check_row.pack(fill="x", pady=(0, sp(10)))
        _checkbutton(
            check_row, "每次备份放到独立的时间戳文件夹", self.pick_snapshot_var
        ).pack(anchor="w")

        holder = form_row(self.mode_box, "保留快照数量", "仅「独立时间戳文件夹」生效")
        spinbox(holder, from_=0, to=500, textvariable=self.keep_var, width=6).pack(
            anchor="w"
        )

    def _render_schedule(self) -> None:
        for child in self.sched_box.winfo_children():
            child.destroy()

        kind = self.sched_var.get()
        if kind == "off":
            return

        if kind == "interval":
            row = tk.Frame(self.sched_box, bg=C.CARD)
            row.pack(fill="x", pady=(0, sp(6)))
            label(row, "每", 9, C.TEXT_DIM, bg=C.CARD).pack(side="left")
            spinbox(row, from_=1, to=10080, textvariable=self.interval_var, width=7).pack(
                side="left", padx=sp(8)
            )
            label(row, "分钟自动备份一次", 9, C.TEXT_DIM, bg=C.CARD).pack(side="left")
            return

        row = tk.Frame(self.sched_box, bg=C.CARD)
        row.pack(fill="x", pady=(0, sp(6)))
        if kind == "weekly":
            label(row, "星期", 9, C.TEXT_DIM, bg=C.CARD).pack(side="left", padx=(0, sp(8)))
            for index in range(1, 8):
                chip = tk.Label(
                    row,
                    text=weekday_name(index),
                    font=font(9),
                    padx=sp(9),
                    pady=sp(5),
                    cursor="hand2",
                )
                chip.pack(side="left", padx=(0, sp(6)))
                chip.bind("<Button-1>", lambda _e, i=index: self._toggle_day(i))
                self._day_chips = getattr(self, "_day_chips", {})
                self._day_chips[index] = chip
            self._paint_days()

        holder = tk.Frame(self.sched_box, bg=C.CARD)
        holder.pack(fill="x", pady=(sp(6), sp(6)))
        label(holder, "时间", 9, C.TEXT_DIM, bg=C.CARD).pack(side="left")
        # tk.Spinbox 在传入 values 时会把文本重置为第一项，这里先存后还原
        current_time = self.time_var.get()
        time_picker = spinbox(
            holder,
            values=[f"{h:02d}:{m:02d}" for h in range(24) for m in (0, 30)],
            textvariable=self.time_var,
            width=7,
        )
        time_picker.pack(side="left", padx=sp(8))
        if current_time:
            self.time_var.set(current_time)
        label(holder, "（24 小时制 HH:MM）", 8, C.TEXT_MUTED, bg=C.CARD).pack(side="left")

    def _toggle_day(self, index: int) -> None:
        if index in self.days:
            if len(self.days) > 1:
                self.days.discard(index)
        else:
            self.days.add(index)
        self._paint_days()

    def _paint_days(self) -> None:
        for index, chip in getattr(self, "_day_chips", {}).items():
            if index in self.days:
                chip.configure(bg=C.ACCENT, fg="#FFFFFF")
            else:
                chip.configure(bg=C.CARD_ALT, fg=C.TEXT_DIM)

    # ------------------------------------------------------------ 选择目录
    def _derived_target(self, name: str) -> str:
        root = self.master_var.get().strip()
        if not root:
            return ""
        return str(Path(root) / sanitize_name(name or "备份"))

    def _update_preview(self) -> None:
        if not hasattr(self, "preview_label"):
            return
        if self.custom_target_var.get():
            text = self.target_var.get().strip() or "（未设置）"
        else:
            text = self._derived_target(self.name_var.get().strip()) or "（未设置主备份文件夹）"
        try:
            self.preview_label.configure(text=f"实际保存到：{text}")
        except tk.TclError:
            pass

    def _on_custom_toggle(self) -> None:
        if not hasattr(self, "custom_box"):
            return
        if self.custom_target_var.get():
            self.custom_box.pack(fill="x")
            if not self.target_var.get().strip():
                self.target_var.set(self._derived_target(self.name_var.get().strip()))
        else:
            self.custom_box.pack_forget()
        self._update_preview()

    def _change_master(self) -> None:
        initial = self.master_var.get() or self.app.config.settings.backup_root
        path = filedialog.askdirectory(
            parent=self, title="选择主备份文件夹", initialdir=initial
        )
        if not path:
            return
        # 这里只暂存，点击「保存任务」时才写全局设置；取消任务不会影响其他任务。
        self.master_var.set(str(Path(path)))
        if not self.custom_target_var.get():
            self.target_var.set(self._derived_target(self.name_var.get().strip()))
        self._update_preview()

    def _pick_target(self) -> None:
        initial = self.target_var.get() or self.app.config.settings.backup_root
        path = filedialog.askdirectory(parent=self, title="选择备份存放位置", initialdir=initial)
        if path:
            self.target_var.set(str(Path(path)))

    # ------------------------------------------------------------ 保存
    def _collect_schedule(self) -> Schedule:
        kind = self.sched_var.get()
        interval = 60
        if kind == "interval":
            interval = parse_int(self.interval_var.get(), "自动备份间隔（分钟）", 1, 10080)
        time_text = self.time_var.get().strip()
        if kind in ("daily", "weekly") and not _valid_time(time_text):
            raise InputError("「自动备份时间」格式应为 HH:MM，例如 22:00。")
        if not _valid_time(time_text):
            time_text = "22:00"
        return Schedule(
            type=kind if kind in ("off", "interval", "daily", "weekly") else "off",
            interval_min=interval,
            time=time_text,
            weekdays=sorted(self.days) or [1, 2, 3, 4, 5],
        )

    def _int(self, var: tk.StringVar, default: int, minimum: int = 0) -> int:
        try:
            return max(minimum, int(str(var.get()).strip() or default))
        except ValueError:
            return default

    def _validate(self, sources: list[str], target: str) -> str | None:
        if not sources:
            return "请至少添加一个要备份的文件或文件夹。"
        for item in sources:
            if not Path(item).exists():
                return f"找不到：\n{item}"
        name = self.name_var.get().strip()
        if name:
            for other in self.app.config.tasks:
                if self.original is not None and other.id == self.original.id:
                    continue
                if other.name.strip().casefold() == name.casefold():
                    return f"任务名称「{name}」已经存在，请换一个名称。"
        try:
            target_res = Path(target).resolve()
        except OSError:
            target_res = Path(target)
        for other in self.app.config.tasks:
            if self.original is not None and other.id == self.original.id:
                continue
            other_target = str(other.target or "").strip()
            if not other_target:
                continue
            try:
                other_res = Path(other_target).resolve()
            except OSError:
                other_res = Path(other_target)
            if target_res == other_res:
                return f"备份目标和任务「{other.name}」相同，请换一个目录。"
            if is_inside(str(target_res), str(other_res)) or is_inside(
                str(other_res), str(target_res)
            ):
                return (
                    f"备份目标不能和任务「{other.name}」的目标目录互相包含：\n"
                    f"本任务：{target}\n其他任务：{other_target}"
                )
        for item in sources:
            path = Path(item)
            try:
                source_res = path.resolve()
            except OSError:
                source_res = path
            if source_res == target_res:
                return "备份目标不能与来源相同。"
            if path.is_dir() and is_inside(target, item):
                return f"备份目标不能放在来源文件夹内部：\n{item}"
            if path.is_dir() and is_inside(item, target):
                return f"来源文件夹不能位于备份目标内部：\n{item}"
        return None

    def _save(self) -> None:
        name = self.name_var.get().strip()

        if not name:
            messagebox.showwarning("请填写名称", "任务名称不能为空。", parent=self)
            return

        if self.custom_target_var.get():
            target = self.target_var.get().strip()
            if not target:
                messagebox.showwarning(
                    "请选择备份目标", "自定义目标目录不能为空。", parent=self
                )
                return
        else:
            master = self.master_var.get().strip()
            if not master:
                messagebox.showwarning(
                    "请选择主备份文件夹",
                    "请先指定主备份文件夹，备份会放在它下面以任务名命名的子文件夹里。",
                    parent=self,
                )
                return
            target = self._derived_target(name)

        problem = self._validate(self.sources, target)
        if problem:
            messagebox.showwarning("无法保存", problem, parent=self)
            return

        if self.original is not None:
            old_one = len(self.original.sources) == 1
            new_one = len(self.sources) == 1
            if old_one != new_one:
                if not messagebox.askyesno(
                    "目录结构会变化",
                    "来源数量从「单个文件夹」变成「多个来源」或反过来，"
                    "备份目标下的目录层级会改变，镜像清理可能把旧层级的文件当作多余文件。\n\n"
                    "确定继续吗？建议先手动确认目标目录，必要时新建任务。",
                    parent=self,
                ):
                    return

        mode = self.mode_var.get()
        exts = normalize_exts([self.pick_exts_var.get()])
        if mode == "pick" and not self.sources:
            messagebox.showwarning("请添加来源", "智能挑选需要至少一个文件夹或文件。", parent=self)
            return

        try:
            schedule = self._collect_schedule()
            keep_versions = parse_int(self.keep_var.get(), "保留快照数量", 0, 500)
            pick_count = parse_int(self.pick_count_var.get(), "智能挑选数量", 1, 9999)
            pick_days = parse_int(self.pick_days_var.get(), "时间范围（天）", 0, 36500)
        except InputError as exc:
            messagebox.showwarning("输入无效", str(exc), parent=self)
            return

        if self.is_new:
            task = Task(id=new_id("t"), name=name, sources=list(self.sources), target=target)
        else:
            task = Task.from_dict(self.original.to_dict())

        task.name = name
        task.sources = list(self.sources)
        task.target = target
        task.mode = mode if mode in ("mirror", "snapshot", "pick") else "mirror"
        task.keep_versions = keep_versions
        task.delete_extraneous = bool(self.extraneous_var.get())
        task.excludes = [
            line.strip() for line in self.excludes_area.get().splitlines() if line.strip()
        ]
        task.enabled = bool(self.enabled_var.get())
        task.schedule = schedule
        task.pick_exts = exts
        task.pick_rule = (
            self.pick_rule_var.get()
            if self.pick_rule_var.get() in ("newest", "largest", "all")
            else "newest"
        )
        task.pick_count = pick_count
        task.pick_days = pick_days
        task.pick_recursive = bool(self.pick_recursive_var.get())
        task.pick_snapshot = bool(self.pick_snapshot_var.get())

        if self.is_new and self.first_run_var.get() == "after5":
            task.bootstrap_at = (datetime.now() + timedelta(minutes=5)).strftime(
                "%Y-%m-%dT%H:%M:%S"
            )
        elif not self.is_new:
            # 编辑旧任务时保留尚未执行的一次性首次备份
            task.bootstrap_at = str(getattr(self.original, "bootstrap_at", "") or "")

        try:
            master = self.master_var.get().strip()
            settings = self.app.config.settings
            if master and master != settings.backup_root:
                settings.backup_root = master
                if not self.app.config.save():
                    messagebox.showerror(
                        "保存失败",
                        f"无法写入主备份文件夹设置：\n"
                        f"{self.app.config.last_save_error or self.app.config.path}",
                        parent=self,
                    )
                    return
                self.app._refresh_sidebar()
        except Exception as exc:  # noqa: BLE001
            messagebox.showwarning("保存失败", f"无法保存主备份文件夹：{exc}", parent=self)
            return

        try:
            Path(target).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showwarning(
                "无法创建目标目录",
                f"{target}\n\n{exc}\n\n请确认磁盘存在且有写入权限。",
                parent=self,
            )
            return

        self.on_save(task, self.is_new)
        self.destroy()


def _valid_time(text: str) -> bool:
    try:
        hour, minute = text.split(":")
        return 0 <= int(hour) <= 23 and 0 <= int(minute) <= 59
    except (ValueError, TypeError):
        return False
