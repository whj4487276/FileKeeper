"""可复用的界面组件。"""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk
from typing import Callable

from . import theme
from .paths import icon_path
from .theme import C, font, sp


# ---------------------------------------------------------------- 图标


class _IconSet:
    def __init__(self):
        self._cache: dict[str, tk.PhotoImage | None] = {}

    def get(self, name: str, variant: str = "", base: int = 24) -> tk.PhotoImage | None:
        key = f"{name}{variant}"
        target = int(round(base * theme.SCALE))
        candidates = (24, 36, 48) if base == 24 else (40, 60, 80)
        chosen = base
        for size in candidates:
            chosen = size
            if target <= size:
                break
        filename = f"{key}.png" if chosen == base else f"{key}_{chosen}.png"
        if filename in self._cache:
            return self._cache[filename]
        image: tk.PhotoImage | None = None
        path = icon_path(filename)
        if path.exists():
            try:
                image = tk.PhotoImage(master=tk._default_root, file=str(path))
            except Exception:
                image = None
        self._cache[filename] = image
        return image


ICONS = _IconSet()


# ---------------------------------------------------------------- 基础控件


def label(
    master,
    text: str = "",
    size: int = 10,
    color: str = C.TEXT,
    weight: str = "normal",
    bg: str = C.BG,
    anchor: str = "w",
    **kwargs,
) -> tk.Label:
    return tk.Label(
        master,
        text=text,
        font=font(size, weight),
        fg=color,
        bg=bg,
        anchor=anchor,
        bd=0,
        highlightthickness=0,
        **kwargs,
    )


def hline(master, color: str = C.BORDER_SOFT, pady: int = 0) -> tk.Frame:
    line = tk.Frame(master, bg=color, height=1)
    line.pack(fill="x", pady=pady)
    return line


_measure_fonts: dict = {}


def fit_text(widget, text: str, max_px: int, size: int = 10) -> str:
    """按实际像素宽度把长文本截断成「头…尾」，用于表格列。"""
    text = str(text or "")
    if max_px <= 0:
        return text
    try:
        key = (str(widget.winfo_toplevel()), size)
        measure = _measure_fonts.get(key)
        if measure is None:
            measure = tkfont.Font(root=widget, font=font(size))
            _measure_fonts[key] = measure
        if measure.measure(text) <= max_px:
            return text
        length = len(text)
        while length > 6:
            length -= 1
            head = length // 2
            tail = length - head
            candidate = text[:head] + "…" + text[-tail:]
            if measure.measure(candidate) <= max_px:
                return candidate
        return text[:length] + "…"
    except Exception:
        return text


def vline(master, color: str = C.BORDER_SOFT) -> tk.Frame:
    return tk.Frame(master, bg=color, width=1)


class Card(tk.Frame):
    def __init__(self, master, padding: int = 18, bg: str | None = None, **kwargs):
        surface = bg or C.CARD
        super().__init__(
            master,
            bg=surface,
            bd=0,
            highlightthickness=1,
            highlightbackground=C.BORDER,
            highlightcolor=C.BORDER,
            **kwargs,
        )
        self.body = tk.Frame(self, bg=surface)
        self.body.pack(fill="both", expand=True, padx=sp(padding), pady=sp(padding))
        self._surface = surface


class Input(tk.Frame):
    """带边框和内边距的输入框。"""

    def __init__(self, master, textvariable: tk.StringVar | None = None, bg: str | None = None):
        surface = bg or C.CARD_ALT
        super().__init__(
            master,
            bg=surface,
            bd=0,
            highlightthickness=1,
            highlightbackground=C.BORDER,
            highlightcolor=C.ACCENT,
        )
        self.entry = tk.Entry(
            self,
            textvariable=textvariable,
            bg=surface,
            fg=C.TEXT,
            insertbackground=C.TEXT,
            relief="flat",
            bd=0,
            highlightthickness=0,
            font=font(10),
            selectbackground=C.ACCENT,
            selectforeground="#FFFFFF",
            readonlybackground=surface,
            disabledbackground=surface,
            disabledforeground=C.TEXT_MUTED,
        )
        self.entry.pack(fill="both", expand=True, padx=sp(9), pady=sp(7))
        self.entry.bind("<FocusIn>", lambda e: self.configure(highlightbackground=C.ACCENT))
        self.entry.bind("<FocusOut>", lambda e: self.configure(highlightbackground=C.BORDER))

    def get(self) -> str:
        return self.entry.get()

    def set(self, value: str) -> None:
        current = self.entry.get()
        if current != value:
            self.entry.delete(0, "end")
            self.entry.insert(0, value)

    def focus(self) -> None:
        self.entry.focus_set()


class TextArea(tk.Frame):
    def __init__(self, master, height: int = 5, bg: str | None = None):
        surface = bg or C.CARD_ALT
        super().__init__(
            master,
            bg=surface,
            bd=0,
            highlightthickness=1,
            highlightbackground=C.BORDER,
            highlightcolor=C.ACCENT,
        )
        self.text = tk.Text(
            self,
            height=height,
            bg=surface,
            fg=C.TEXT,
            insertbackground=C.TEXT,
            relief="flat",
            bd=0,
            highlightthickness=0,
            font=font(10),
            selectbackground=C.ACCENT,
            selectforeground="#FFFFFF",
            padx=sp(8),
            pady=sp(6),
            wrap="none",
            undo=True,
        )
        self.scroll = ttk.Scrollbar(self, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=self.scroll.set)
        self.text.pack(side="left", fill="both", expand=True)
        self.scroll.pack(side="right", fill="y")
        self.text.bind("<FocusIn>", lambda e: self.configure(highlightbackground=C.ACCENT))
        self.text.bind("<FocusOut>", lambda e: self.configure(highlightbackground=C.BORDER))

    def get(self) -> str:
        return self.text.get("1.0", "end-1c")

    def set(self, value: str) -> None:
        self.text.delete("1.0", "end")
        self.text.insert("1.0", value)


_PALETTE = {
    "primary": dict(bg=C.ACCENT, fg="#FFFFFF", hover=C.ACCENT_HOVER),
    "secondary": dict(bg=C.CARD_ALT, fg=C.TEXT, hover=C.CARD_HOVER),
    "ghost": dict(bg=C.CARD, fg=C.TEXT_DIM, hover=C.CARD_HOVER),
    "subtle": dict(bg=C.BG, fg=C.TEXT_DIM, hover=C.CARD_ALT),
    "danger": dict(bg=C.RED_SOFT, fg=C.RED, hover="#4A2A31"),
    "success": dict(bg=C.GREEN_SOFT, fg=C.GREEN, hover="#1B4034"),
    "sidebar": dict(bg=C.SIDEBAR, fg=C.TEXT_DIM, hover=C.CARD_ALT),
}


class FlatButton(tk.Button):
    def __init__(
        self,
        master,
        text: str = "",
        command: Callable | None = None,
        kind: str = "primary",
        icon: tk.PhotoImage | None = None,
        padx: int = 15,
        pady: int = 7,
        font_size: int = 10,
        bold: bool | None = None,
        **kwargs,
    ):
        self._pal = _PALETTE.get(kind, _PALETTE["primary"])
        if bold is None:
            bold = kind == "primary"
        super().__init__(
            master,
            text=text,
            command=command,
            bg=self._pal["bg"],
            fg=self._pal["fg"],
            activebackground=self._pal["hover"],
            activeforeground=self._pal["fg"],
            disabledforeground=C.TEXT_MUTED,
            relief="flat",
            bd=0,
            highlightthickness=0,
            takefocus=0,
            cursor="hand2",
            font=font(font_size, "bold" if bold else "normal"),
            padx=sp(padx),
            pady=sp(pady),
            image=icon,
            compound="left" if icon is not None else "none",
            **kwargs,
        )
        self._enabled = True
        self.bind("<Enter>", self._on_enter, add="+")
        self.bind("<Leave>", self._on_leave, add="+")

    def _on_enter(self, _event=None):
        if self._enabled:
            self.configure(bg=self._pal["hover"])

    def _on_leave(self, _event=None):
        if self._enabled:
            self.configure(bg=self._pal["bg"])

    def set_enabled(self, value: bool) -> None:
        self._enabled = bool(value)
        self.configure(
            state="normal" if value else "disabled",
            bg=self._pal["bg"] if value else C.CARD,
            cursor="hand2" if value else "arrow",
        )

    def set_kind(self, kind: str) -> None:
        """切换按钮配色（primary / secondary / success …）。"""
        palette = _PALETTE.get(kind)
        if palette is None or palette is self._pal:
            return
        self._pal = palette
        self.configure(
            bg=palette["bg"],
            fg=palette["fg"],
            activebackground=palette["hover"],
            activeforeground=palette["fg"],
        )


class Segmented(tk.Frame):
    """轻量分段选择器，替代 Radio 按钮。"""

    def __init__(self, master, options, variable: tk.StringVar, bg: str = C.CARD):
        super().__init__(master, bg=bg)
        self.variable = variable
        self._bg = bg
        self._buttons: dict[str, tk.Label] = {}
        for value, text in options:
            widget = tk.Label(
                self,
                text=text,
                font=font(9),
                padx=sp(14),
                pady=sp(7),
                bd=0,
                highlightthickness=0,
                cursor="hand2",
            )
            widget.pack(side="left", padx=(0, sp(8)))
            widget.bind("<Button-1>", lambda _e, v=value: self.variable.set(v))
            self._buttons[value] = widget
        self.variable.trace_add("write", lambda *_: self._paint())
        self._paint()

    def _paint(self) -> None:
        current = self.variable.get()
        for value, widget in self._buttons.items():
            if value == current:
                widget.configure(bg=C.ACCENT, fg="#FFFFFF")
            else:
                widget.configure(bg=C.CARD_ALT, fg=C.TEXT_DIM)


class StatusDot(tk.Canvas):
    def __init__(self, master, color: str = C.TEXT_MUTED, size: int = 8, bg: str = C.CARD):
        pixel = sp(size)
        super().__init__(
            master, width=pixel, height=pixel, bg=bg, highlightthickness=0, bd=0, takefocus=0
        )
        self._size = pixel
        inset = max(1, sp(1))
        self._dot = self.create_oval(
            inset, inset, pixel - inset, pixel - inset, fill=color, outline=""
        )

    def set_color(self, color: str) -> None:
        self.itemconfigure(self._dot, fill=color)


class Badge(tk.Label):
    def __init__(self, master, text: str = "", fg: str = C.ACCENT, bg: str = C.ACCENT_SOFT):
        super().__init__(
            master,
            text=text,
            fg=fg,
            bg=bg,
            font=font(8, "bold"),
            padx=7,
            pady=2,
            bd=0,
            highlightthickness=0,
        )


class ScrollFrame(tk.Frame):
    """带垂直滚动条的容器，内容放在 .body 中。"""

    _registry: list["ScrollFrame"] = []

    def __init__(self, master, bg: str | None = None, **kwargs):
        surface = bg or C.BG
        super().__init__(master, bg=surface, bd=0, highlightthickness=0, **kwargs)
        self.surface = surface
        self.canvas = tk.Canvas(
            self,
            bg=surface,
            highlightthickness=0,
            bd=0,
            takefocus=0,
            yscrollincrement=sp(24),
        )
        self.scroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.body = tk.Frame(self.canvas, bg=surface)
        self._window = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scroll.pack(side="right", fill="y")
        self.body.bind("<Configure>", self._on_inner)
        self.canvas.bind("<Configure>", self._on_canvas)
        ScrollFrame._registry.append(self)
        self.bind("<Destroy>", self._on_destroy, add="+")

    def _on_destroy(self, event=None):
        if event is not None and event.widget is not self:
            return
        try:
            ScrollFrame._registry.remove(self)
        except ValueError:
            pass

    def _on_inner(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas(self, event):
        self.canvas.itemconfigure(self._window, width=event.width)

    def scroll_by(self, delta: int) -> None:
        if not self.canvas.winfo_exists():
            return
        first, last = self.canvas.yview()
        if first <= 0.0 and last >= 1.0:
            return
        self.canvas.yview_scroll(-3 if delta > 0 else 3, "units")

    def contains(self, widget) -> bool:
        node = widget
        while node is not None:
            if node is self.body or node is self.canvas:
                return True
            node = getattr(node, "master", None)
        return False


def install_wheel_router(root: tk.Misc) -> None:
    """全窗口滚动分发：找到指针下方最内层的 ScrollFrame。"""

    def handler(event):
        try:
            widget = root.winfo_containing(event.x_root, event.y_root)
        except (KeyError, tk.TclError):
            return
        for frame in reversed(ScrollFrame._registry):
            if frame.contains(widget):
                frame.scroll_by(event.delta)
                return

    root.bind_all("<MouseWheel>", handler, add="+")


# ---------------------------------------------------------------- 组合组件


class StatCard(Card):
    def __init__(self, master, title: str, value: str = "—", sub: str = "", accent: str = C.ACCENT):
        super().__init__(master, padding=18)
        head = tk.Frame(self.body, bg=C.CARD)
        head.pack(fill="x")
        tk.Frame(head, bg=accent, width=sp(3), height=sp(11)).pack(side="left", pady=sp(1))
        label(head, title, 9, C.TEXT_DIM, bg=C.CARD).pack(side="left", padx=(sp(8), 0))
        self.value = label(self.body, value, 19, C.TEXT, "bold", bg=C.CARD)
        self.value.pack(fill="x", pady=(sp(9), sp(1)))
        self.sub = label(self.body, sub, 9, C.TEXT_MUTED, bg=C.CARD)
        self.sub.pack(fill="x")

    def set(self, value: str | None = None, sub: str | None = None) -> None:
        if value is not None:
            self.value.configure(text=value)
        if sub is not None:
            self.sub.configure(text=sub)


class NavButton(tk.Frame):
    def __init__(self, master, key: str, text: str, icon_name: str, command: Callable[[str], None]):
        super().__init__(master, bg=C.SIDEBAR, height=sp(46), cursor="hand2")
        self.pack_propagate(False)
        self.key = key
        self._command = command
        self._icon_name = icon_name
        self._active = False
        self._hover = False
        self._image: tk.PhotoImage | None = None

        self.bar = tk.Frame(self, bg=C.SIDEBAR, width=sp(3))
        self.bar.place(x=0, y=sp(10), width=sp(3), height=sp(26))

        self.icon = tk.Label(self, bg=C.SIDEBAR, bd=0, highlightthickness=0)
        self.icon.pack(side="left", padx=(sp(16), sp(11)))

        self.text = label(self, text, 10, C.TEXT_DIM, bg=C.SIDEBAR)
        self.text.pack(side="left", fill="x", expand=True)

        for widget in (self, self.icon, self.text):
            widget.bind("<Button-1>", self._on_click)
            widget.bind("<Enter>", self._on_enter)
            widget.bind("<Leave>", self._on_leave)

        self._apply()

    def _on_click(self, _event=None):
        self._command(self.key)

    def _on_enter(self, _event=None):
        self._hover = True
        self._apply()

    def _on_leave(self, _event=None):
        self._hover = False
        self._apply()

    def set_active(self, active: bool) -> None:
        self._active = bool(active)
        self._apply()

    def _apply(self) -> None:
        if self._active:
            background = C.CARD_ALT
            foreground = C.TEXT
        elif self._hover:
            background = C.SIDEBAR_HOVER
            foreground = C.TEXT
        else:
            background = C.SIDEBAR
            foreground = C.TEXT_DIM

        self.configure(bg=background)
        for widget in (self.icon, self.text, self.bar):
            widget.configure(bg=background)
        self.text.configure(fg=foreground)
        self.bar.configure(bg=C.ACCENT if self._active else background)

        image = ICONS.get(self._icon_name, "_active" if self._active else "")
        if image is not None:
            self._image = image
            self.icon.configure(image=image)
        else:
            self.icon.configure(text="•", fg=foreground, font=font(12, "bold"))


class EmptyState(tk.Frame):
    def __init__(self, master, title: str, hint: str = "", bg: str = C.CARD):
        super().__init__(master, bg=bg)
        holder = tk.Frame(self, bg=bg)
        holder.place(relx=0.5, rely=0.45, anchor="center")
        label(holder, title, 11, C.TEXT_DIM, "bold", bg=bg).pack()
        if hint:
            label(holder, hint, 9, C.TEXT_MUTED, bg=bg).pack(pady=(6, 0))


def form_row(master, title: str, hint: str = "", bg: str = C.CARD) -> tk.Frame:
    """构造函数表单的一行，返回用于放置控件的容器。"""
    row = tk.Frame(master, bg=bg)
    row.pack(fill="x", pady=(0, sp(16)))
    head = tk.Frame(row, bg=bg)
    head.pack(fill="x", pady=(0, sp(7)))
    label(head, title, 9, C.TEXT_DIM, bg=bg).pack(side="left")
    if hint:
        label(head, hint, 8, C.TEXT_MUTED, bg=bg).pack(side="left", padx=(sp(8), 0))
    holder = tk.Frame(row, bg=bg)
    holder.pack(fill="x")
    return holder


def run_bg(widget: tk.Misc, work: Callable, on_done: Callable | None = None, interval: int = 120):
    """在后台线程执行 work，并在主线程回调 on_done(kind, value)。"""
    results: queue.Queue = queue.Queue()

    def runner():
        try:
            results.put(("ok", work()))
        except Exception as exc:  # noqa: BLE001 - 需要把异常带回主线程
            results.put(("err", exc))

    threading.Thread(target=runner, daemon=True).start()

    def poll():
        try:
            kind, value = results.get_nowait()
        except queue.Empty:
            if widget.winfo_exists():
                widget.after(interval, poll)
            return
        if on_done is not None and widget.winfo_exists():
            on_done(kind, value)

    widget.after(interval, poll)


def center_over(window: tk.Toplevel, parent: tk.Misc) -> None:
    try:
        window.update_idletasks()
        width = window.winfo_width()
        height = window.winfo_height()
        px = parent.winfo_rootx()
        py = parent.winfo_rooty()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        x = max(0, px + (pw - width) // 2)
        y = max(0, py + (ph - height) // 3)
        window.geometry(f"+{x}+{y}")
    except tk.TclError:
        pass


def make_progress(master, style: str = "Bar.Horizontal.TProgressbar") -> ttk.Progressbar:
    return ttk.Progressbar(master, orient="horizontal", mode="determinate", style=style)


def spinbox(
    master,
    from_: int = 0,
    to: int = 100,
    textvariable: tk.StringVar | None = None,
    width: int = 6,
    values: list[str] | None = None,
) -> tk.Spinbox:
    kwargs = dict(
        bg=C.CARD_ALT,
        fg=C.TEXT,
        insertbackground=C.TEXT,
        buttonbackground=C.CARD_ALT,
        background=C.CARD_ALT,
        disabledbackground=C.CARD,
        disabledforeground=C.TEXT_MUTED,
        relief="flat",
        bd=0,
        highlightthickness=1,
        highlightbackground=C.BORDER,
        highlightcolor=C.ACCENT,
        font=font(10),
        justify="center",
        width=width,
        buttoncursor="hand2",
    )
    if values is not None:
        kwargs["values"] = values
    else:
        kwargs["from_"] = from_
        kwargs["to"] = to
    return tk.Spinbox(master, textvariable=textvariable, **kwargs)


__all__ = [
    "Badge",
    "Card",
    "EmptyState",
    "FlatButton",
    "ICONS",
    "Input",
    "NavButton",
    "ScrollFrame",
    "Segmented",
    "StatCard",
    "StatusDot",
    "TextArea",
    "center_over",
    "fit_text",
    "form_row",
    "hline",
    "install_wheel_router",
    "label",
    "make_progress",
    "run_bg",
    "spinbox",
    "theme",
    "vline",
]
