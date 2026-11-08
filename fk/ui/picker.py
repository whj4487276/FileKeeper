"""支持隐藏项的文件 / 文件夹选择器（备份来源使用）。

Windows 原生对话框是否显示隐藏项取决于资源管理器设置，且 tkinter 没有
对应的开关。这里自己用 ``os.scandir`` 枚举，默认显示隐藏项、可选显示系统项，
并把目录读取放到后台线程，避免网络路径卡住界面。
"""
from __future__ import annotations

import ctypes
import os
import stat
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk

from ..fsutil import human_size, long_path
from ..paths import pictures_dir
from ..theme import C, font, sp
from ..widgets import FlatButton, Input, center_over, label

SCAN_TIMEOUT = 8.0
FILE_ATTRIBUTE_HIDDEN = getattr(stat, "FILE_ATTRIBUTE_HIDDEN", 0x2)
FILE_ATTRIBUTE_SYSTEM = getattr(stat, "FILE_ATTRIBUTE_SYSTEM", 0x4)
FILE_ATTRIBUTE_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


@dataclass
class PickerEntry:
    name: str
    path: str
    is_dir: bool
    hidden: bool = False
    system: bool = False
    is_link: bool = False
    size: int | None = None
    mtime: float = 0.0


def available_drives() -> list[str]:
    """当前可用盘符，形如 ``["C:\\", "D:\\"]``。"""
    try:
        drives = list(os.listdrives())  # Python 3.12+
        if drives:
            return drives
    except Exception:
        pass
    try:
        mask = int(ctypes.windll.kernel32.GetLogicalDrives())
        drives = []
        for index in range(26):
            if mask & (1 << index):
                drives.append(f"{chr(ord('A') + index)}:\\")
        return drives
    except Exception:
        return []


def normalize_dir(raw: str, base: str = "") -> str:
    text = str(raw or "").strip().strip('"')
    if not text:
        return ""
    text = os.path.expandvars(os.path.expanduser(text))
    if len(text) == 2 and text[1] == ":" and text[0].isalpha():
        text += "\\"
    if not os.path.isabs(text) and not text.startswith("\\\\"):
        text = os.path.join(base or os.getcwd(), text)
    try:
        text = os.path.normpath(text)
    except Exception:
        pass
    if len(text) == 2 and text[1] == ":" and text[0].isalpha():
        text += "\\"
    return text


def scan_directory(path: str) -> tuple[list[PickerEntry], str]:
    """枚举目录，不做隐藏过滤；返回 ``(条目, 错误)``。"""
    text = str(path or "")
    if not text:
        return [], "路径为空"
    scan_path = long_path(text)
    try:
        entries: list[PickerEntry] = []
        with os.scandir(scan_path) as iterator:
            for dirent in iterator:
                name = dirent.name
                try:
                    info = dirent.stat(follow_symlinks=False)
                    attributes = int(getattr(info, "st_file_attributes", 0) or 0)
                    is_dir = stat.S_ISDIR(info.st_mode)
                    hidden = bool(attributes & FILE_ATTRIBUTE_HIDDEN) or name.startswith(".")
                    system = bool(attributes & FILE_ATTRIBUTE_SYSTEM)
                    is_link = stat.S_ISLNK(info.st_mode) or bool(
                        attributes & FILE_ATTRIBUTE_REPARSE_POINT
                    )
                    size = None if is_dir else int(getattr(info, "st_size", 0) or 0)
                    mtime = float(getattr(info, "st_mtime", 0.0) or 0.0)
                except OSError:
                    is_dir = False
                    hidden = name.startswith(".")
                    system = False
                    is_link = False
                    size = None
                    mtime = 0.0
                entries.append(
                    PickerEntry(
                        name=name,
                        path=os.path.join(text, name),
                        is_dir=is_dir,
                        hidden=hidden,
                        system=system,
                        is_link=is_link,
                        size=size,
                        mtime=mtime,
                    )
                )
    except PermissionError:
        return [], f"没有权限访问这个文件夹：\n{text}"
    except FileNotFoundError:
        return [], f"文件夹不存在：\n{text}"
    except NotADirectoryError:
        return [], "这是一个文件，不是文件夹"
    except OSError as exc:
        return [], f"无法读取文件夹：\n{text}\n\n{exc}"

    entries.sort(key=lambda item: (not item.is_dir, item.name.casefold()))
    return entries, ""


def filter_entries(
    entries: list[PickerEntry], show_hidden: bool, show_system: bool
) -> list[PickerEntry]:
    """按界面开关过滤；打开系统项时，系统项自带的隐藏属性也一并显示。"""
    result: list[PickerEntry] = []
    for entry in entries:
        if entry.system and not show_system:
            continue
        if entry.hidden and not (show_hidden or (entry.system and show_system)):
            continue
        result.append(entry)
    return result


class HiddenAwarePicker(tk.Toplevel):
    """可多选的文件/文件夹选择器。

    用法::

        picker = HiddenAwarePicker(parent, mode="folders")
        parent.wait_window(picker)
        paths = picker.result
    """

    _last_dir = ""
    _last_show_hidden = True
    _last_show_system = False

    def __init__(
        self,
        parent,
        mode: str = "files",
        initial_dir: str | None = None,
        title: str | None = None,
    ):
        super().__init__(parent)
        self.parent = parent
        self.mode = "folders" if mode == "folders" else "files"
        self.result: list[str] = []
        self._closed = False
        self._current = ""
        self._target = ""
        self._all_entries: list[PickerEntry] = []
        self._row_map: dict[str, PickerEntry] = {}
        self._serial = 0
        self._loading = False
        self._load_started = 0.0
        self._load_result = None

        self.title(
            title
            or ("选择要备份的文件夹" if self.mode == "folders" else "选择要备份的文件")
        )
        self.configure(bg=C.BG)
        self.resizable(True, True)
        try:
            self.transient(parent)
        except tk.TclError:
            pass
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda _event: self._cancel())
        self.bind("<F5>", lambda _event: self._navigate(self._current))

        self._build()
        self._place_window()
        start = (
            initial_dir
            or self._last_dir
            or str(Path.home())
        )
        self._navigate(start)
        self.after(80, self._bring_front)

    # ------------------------------------------------------------ 布局
    def _build(self) -> None:
        outer = tk.Frame(self, bg=C.BG)
        outer.pack(fill="both", expand=True, padx=sp(18), pady=sp(14))

        top = tk.Frame(outer, bg=C.BG)
        top.pack(fill="x")
        self.up_button = FlatButton(
            top,
            "↑ 上级",
            command=self._go_up,
            kind="secondary",
            font_size=9,
            padx=10,
        )
        self.up_button.pack(side="left")

        self.path_var = tk.StringVar()
        self.path_input = Input(top, self.path_var)
        self.path_input.pack(side="left", fill="x", expand=True, padx=(sp(8), sp(8)))
        self.path_input.entry.bind("<Return>", lambda _event: self._go())
        FlatButton(
            top, "转到", command=self._go, kind="secondary", font_size=9, padx=10
        ).pack(side="left")
        FlatButton(
            top, "刷新", command=self._refresh, kind="ghost", font_size=9, padx=9
        ).pack(side="left", padx=(sp(6), 0))

        drive_row = tk.Frame(outer, bg=C.BG)
        drive_row.pack(fill="x", pady=(sp(8), 0))
        label(drive_row, "位置", 8, C.TEXT_MUTED, bg=C.BG).pack(side="left")
        for drive in available_drives():
            FlatButton(
                drive_row,
                drive.rstrip("\\"),
                command=lambda path=drive: self._navigate(path),
                kind="ghost",
                font_size=8,
                padx=8,
                pady=3,
                bold=False,
            ).pack(side="left", padx=(sp(5), 0))
        for text, path in (
            ("主目录", str(Path.home())),
            ("图片", str(pictures_dir())),
        ):
            if os.path.isdir(long_path(path)):
                FlatButton(
                    drive_row,
                    text,
                    command=lambda target=path: self._navigate(target),
                    kind="ghost",
                    font_size=8,
                    padx=8,
                    pady=3,
                    bold=False,
                ).pack(side="left", padx=(sp(5), 0))

        filters = tk.Frame(outer, bg=C.BG)
        filters.pack(fill="x", pady=(sp(8), sp(6)))
        self.show_hidden_var = tk.BooleanVar(value=self._last_show_hidden)
        self.show_system_var = tk.BooleanVar(value=self._last_show_system)
        self._check(filters, "显示隐藏项", self.show_hidden_var).pack(side="left")
        self._check(filters, "显示系统项", self.show_system_var).pack(
            side="left", padx=(sp(14), 0)
        )
        label(
            filters,
            "（系统项通常包含回收站/卷信息，建议只在需要时打开）",
            8,
            C.TEXT_MUTED,
            bg=C.BG,
        ).pack(side="left", padx=(sp(8), 0))

        table = tk.Frame(outer, bg=C.CARD)
        table.pack(fill="both", expand=True)
        table.grid_rowconfigure(0, weight=1)
        table.grid_columnconfigure(0, weight=1)

        columns = ("name", "type", "size", "modified", "attr")
        self.tree = ttk.Treeview(
            table,
            columns=columns,
            show="headings",
            selectmode="extended",
            style="Data.Treeview",
        )
        headings = {
            "name": ("名称", 360),
            "type": ("类型", 76),
            "size": ("大小", 90),
            "modified": ("修改时间", 138),
            "attr": ("属性", 110),
        }
        for key, (text, width) in headings.items():
            self.tree.heading(key, text=text, anchor="w")
            self.tree.column(key, width=sp(width), minwidth=sp(50), anchor="w")
        self.tree.tag_configure("hidden", foreground=C.TEXT_MUTED)
        self.tree.tag_configure("system", foreground=C.AMBER)
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree.bind("<Double-Button-1>", self._on_double)
        self.tree.bind("<Return>", self._on_return)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        vbar = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        hbar = ttk.Scrollbar(table, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vbar.set, xscrollcommand=hbar.set)
        vbar.grid(row=0, column=1, sticky="ns")
        hbar.grid(row=1, column=0, sticky="ew")

        self.status_label = label(
            outer, "正在读取…", 8, C.TEXT_DIM, bg=C.BG, wraplength=sp(900)
        )
        self.status_label.pack(anchor="w", pady=(sp(6), 0))

        bottom = tk.Frame(outer, bg=C.BG)
        bottom.pack(fill="x", pady=(sp(8), 0))
        self.selected_label = label(bottom, "", 8, C.TEXT_MUTED, bg=C.BG)
        self.selected_label.pack(side="left")
        FlatButton(bottom, "取消", command=self._cancel, kind="ghost").pack(
            side="right"
        )
        FlatButton(
            bottom,
            "添加选中",
            command=self._accept_selected,
            padx=20,
        ).pack(side="right", padx=(0, sp(8)))
        if self.mode == "folders":
            FlatButton(
                bottom,
                "选择当前文件夹",
                command=self._accept_current,
                kind="secondary",
                font_size=9,
            ).pack(side="right", padx=(0, sp(8)))

    def _check(self, master, text: str, variable: tk.BooleanVar):
        return tk.Checkbutton(
            master,
            text=text,
            variable=variable,
            command=self._on_filter_change,
            bg=C.BG,
            fg=C.TEXT,
            activebackground=C.BG,
            activeforeground=C.TEXT,
            selectcolor=C.BG_DEEP,
            highlightthickness=0,
            bd=0,
            anchor="w",
            font=font(8),
            cursor="hand2",
        )

    def _place_window(self) -> None:
        self.update_idletasks()
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        width = min(sp(1040), max(sp(760), screen_w - sp(160)))
        height = min(sp(680), max(sp(500), screen_h - sp(160)))
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 4)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.minsize(sp(720), sp(460))

    def _bring_front(self) -> None:
        try:
            self.lift()
            center_over(self, self.parent)
            self.grab_set()
            self.path_input.focus()
        except tk.TclError:
            pass

    # ------------------------------------------------------------ 导航
    def _go(self) -> None:
        text = normalize_dir(self.path_var.get(), self._current)
        if not text:
            return
        # 文件类型判断也放到后台扫描里，避免在 UNC 路径上同步探测卡住 UI。
        self._navigate(text)

    def _refresh(self) -> None:
        self._navigate(self._current or self.path_var.get())

    def _go_up(self) -> None:
        current = self._current
        if not current:
            return
        parent = os.path.dirname(current.rstrip("\\/"))
        if not parent or parent == current:
            return
        self._navigate(parent)

    def _navigate(self, path: str) -> None:
        target = normalize_dir(path, self._current)
        if not target:
            return
        self._serial += 1
        serial = self._serial
        self._target = target
        self._loading = True
        self._load_started = time.monotonic()
        self._load_result = None
        self.path_var.set(target)
        self.tree.delete(*self.tree.get_children())
        self._row_map.clear()
        self.status_label.configure(text=f"正在读取：{target}", fg=C.TEXT_DIM)
        self.selected_label.configure(text="")

        def work() -> None:
            entries, error = scan_directory(target)
            self._load_result = (serial, target, entries, error)

        threading.Thread(target=work, name="fk-picker-scan", daemon=True).start()
        self.after(60, self._poll_load)

    def _poll_load(self) -> None:
        if self._closed:
            return
        if not self._loading:
            return
        if time.monotonic() - self._load_started > SCAN_TIMEOUT:
            self._loading = False
            self._serial += 1
            self._set_error(f"读取超时（{SCAN_TIMEOUT:.0f} 秒）：\n{self._target}")
            self.path_var.set(self._current)
            return
        result = self._load_result
        if result is None or result[0] != self._serial:
            self.after(60, self._poll_load)
            return

        _serial, target, entries, error = result
        self._loading = False
        if error:
            self._set_error(error)
            self.path_var.set(self._current)
            return
        self._current = target
        self._all_entries = entries
        self.path_var.set(target)
        self._render()

    def _set_error(self, message: str) -> None:
        self.status_label.configure(text=message, fg=C.RED)
        self.selected_label.configure(text="")
        try:
            self.up_button.set_enabled(bool(self._current))
        except tk.TclError:
            pass

    # ------------------------------------------------------------ 列表
    def _on_filter_change(self) -> None:
        HiddenAwarePicker._last_show_hidden = bool(self.show_hidden_var.get())
        HiddenAwarePicker._last_show_system = bool(self.show_system_var.get())
        if self._loading:
            return
        self._render()

    def _render(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self._row_map.clear()
        visible = filter_entries(
            self._all_entries,
            bool(self.show_hidden_var.get()),
            bool(self.show_system_var.get()),
        )
        for index, entry in enumerate(visible):
            attrs = []
            if entry.hidden:
                attrs.append("隐藏")
            if entry.system:
                attrs.append("系统")
            if entry.is_link:
                attrs.append("链接")
            kind = "文件夹" if entry.is_dir else "文件"
            if entry.is_link and entry.is_dir:
                kind = "文件夹链接"
            elif entry.is_link:
                kind = "文件链接"
            size = "—" if entry.is_dir or entry.size is None else human_size(entry.size)
            modified = ""
            if entry.mtime:
                try:
                    modified = datetime.fromtimestamp(entry.mtime).strftime(
                        "%Y-%m-%d %H:%M"
                    )
                except (OSError, ValueError):
                    modified = ""
            tags = ("system",) if entry.system else (("hidden",) if entry.hidden else ())
            item = str(index)
            self.tree.insert(
                "",
                "end",
                iid=item,
                values=(
                    entry.name,
                    kind,
                    size,
                    modified,
                    " · ".join(attrs),
                ),
                tags=tags,
            )
            self._row_map[item] = entry
        hidden_count = sum(1 for item in self._all_entries if item.hidden)
        system_count = sum(1 for item in self._all_entries if item.system)
        self.status_label.configure(
            text=(
                f"显示 {len(visible)} / 共 {len(self._all_entries)} 项"
                f"　隐藏 {hidden_count} 项 · 系统 {system_count} 项"
            ),
            fg=C.TEXT_DIM,
        )
        self.selected_label.configure(text="")
        try:
            self.up_button.set_enabled(bool(self._current))
        except tk.TclError:
            pass

    # ------------------------------------------------------------ 选择
    def _selected_entries(self) -> list[PickerEntry]:
        result = []
        for item in self.tree.selection():
            entry = self._row_map.get(item)
            if entry is not None:
                result.append(entry)
        return result

    def _on_select(self, _event=None) -> None:
        selected = self._selected_entries()
        if not selected:
            self.selected_label.configure(text="")
            return
        if len(selected) == 1:
            self.selected_label.configure(text=selected[0].path)
        else:
            self.selected_label.configure(text=f"已选 {len(selected)} 项")

    def _on_double(self, event=None) -> None:
        if event is not None:
            item = self.tree.identify_row(event.y)
        else:
            selection = self.tree.selection()
            item = selection[0] if selection else ""
        entry = self._row_map.get(item)
        if entry is None:
            return
        if entry.is_dir:
            self._navigate(entry.path)
        elif self.mode == "files":
            self._accept_paths([entry.path])
        else:
            messagebox.showinfo("请选择文件夹", "双击文件夹进入；文件不能作为文件夹来源。", parent=self)

    def _on_return(self, _event=None) -> None:
        selected = self._selected_entries()
        if len(selected) == 1 and selected[0].is_dir:
            self._navigate(selected[0].path)
        else:
            self._accept_selected()

    def _accept_selected(self) -> None:
        selected = self._selected_entries()
        want_dir = self.mode == "folders"
        matching = [entry for entry in selected if entry.is_dir == want_dir]
        if not matching:
            messagebox.showinfo(
                "请选择",
                "请选择一个文件夹。" if want_dir else "请选择一个文件。\n双击文件夹可以进入。",
                parent=self,
            )
            return
        self._accept_paths([entry.path for entry in matching])

    def _accept_current(self) -> None:
        if self.mode != "folders" or not self._current:
            return
        self._accept_paths([self._current])

    def _accept_paths(self, paths: list[str]) -> None:
        unique: list[str] = []
        for path in paths:
            text = str(path)
            if text and text not in unique:
                unique.append(text)
        if not unique:
            return
        self.result = unique
        if self._current:
            HiddenAwarePicker._last_dir = self._current
        self._close()

    def _cancel(self) -> None:
        self.result = []
        self._close()

    def _close(self) -> None:
        self._closed = True
        self._serial += 1
        try:
            self.grab_release()
        except tk.TclError:
            pass
        try:
            self.destroy()
        except tk.TclError:
            pass


def pick_paths(
    parent,
    mode: str = "files",
    initial_dir: str | None = None,
) -> list[str]:
    """打开选择器并等待用户完成，返回选中的路径列表。"""
    picker = HiddenAwarePicker(parent, mode=mode, initial_dir=initial_dir)
    try:
        parent.wait_window(picker)
    except tk.TclError:
        return []
    return list(picker.result)
