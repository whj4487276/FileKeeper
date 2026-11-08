"""计时器页：2×5 面板，10 个互相独立的计时器。"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox

from .. import alarm as alarm_mod
from .. import timers as timers_mod
from ..inpututils import InputError, parse_int
from ..theme import C, font, sp
from ..widgets import (
    Card,
    FlatButton,
    Input,
    Segmented,
    center_over,
    fit_text,
    form_row,
    label,
    spinbox,
)
from .base import Page

INK = "#000000"
ON_COLOR = "#3ECF8E"  # 正计时工作中：绿色
OFF_COLOR = "#FFFFFF"  # 未工作：白色
DOWN_COLOR = "#FF3B30"  # 倒计时：红色
SEP_COLOR = "#1E1E1E"
YELLOW = "#FFD400"
TITLE_RED = "#FF2D2D"

TIME_FONT = ("Consolas", 25, "bold")
INDEX_FONT = ("Microsoft YaHei UI", 13, "bold")
TITLE_FONT = ("Microsoft YaHei UI", 11, "bold")

ADVICE = "单击序号可在「序号 / 标题」之间切换；点击下方标题进入详细设置"


class TimerAlertDialog(tk.Toplevel):
    """倒计时结束弹窗：大标题红字 + 黑白黄闪烁背景 + 可选持续响铃。"""

    def __init__(self, master, title: str, message: str, sound: bool = False):
        super().__init__(master)
        self.title("计时结束")
        self.configure(bg=YELLOW)
        self.resizable(False, False)
        try:
            self.attributes("-topmost", True)
        except tk.TclError:
            pass

        width, height = sp(560), sp(300)
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        self.geometry(
            f"{width}x{height}+{(screen_w - width) // 2}+{(screen_h - height) // 3}"
        )

        self._stop_event = threading.Event()
        self._flash_job = None

        self.head = tk.Label(
            self,
            text=title or "计时结束",
            bg=INK,
            fg=TITLE_RED,
            font=("Microsoft YaHei UI", 33, "bold"),
            pady=sp(26),
            wraplength=width - sp(30),
        )
        self.head.pack(fill="x")

        body = tk.Frame(self, bg=YELLOW)
        body.pack(fill="both", expand=True, padx=sp(26), pady=(sp(20), sp(20)))

        tk.Label(
            body,
            text=message or "计时结束",
            bg=YELLOW,
            fg="#000000",
            font=("Microsoft YaHei UI", 12),
            wraplength=width - sp(70),
            justify="center",
            anchor="center",
        ).pack(fill="x", anchor="center")

        footer = tk.Frame(body, bg=YELLOW)
        footer.pack(fill="x", side="bottom")
        FlatButton(
            footer, "知道了", command=self.destroy, kind="secondary", padx=26, pady=7
        ).pack(side="right")

        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda _e: self.destroy())
        self._flash(True)

        if sound:
            threading.Thread(target=self._beep_loop, daemon=True).start()

        try:
            self.lift()
            self.focus_force()
        except tk.TclError:
            pass

    def _flash(self, on: bool) -> None:
        try:
            self.head.configure(bg=YELLOW if on else INK)
        except tk.TclError:
            return
        self._flash_job = self.after(430, lambda: self._flash(not on))

    def _beep_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                alarm_mod.play_beep_once()
            except Exception:
                pass
            self._stop_event.wait(0.2)

    def destroy(self) -> None:
        self._stop_event.set()
        if self._flash_job is not None:
            try:
                self.after_cancel(self._flash_job)
            except Exception:
                pass
            self._flash_job = None
        try:
            super().destroy()
        except tk.TclError:
            pass


class TimerDialog(tk.Toplevel):
    """单个计时器的详细设置。"""

    def __init__(self, app, timer: timers_mod.Timer, on_save):
        super().__init__(app)
        self.app = app
        self.timer = timer
        self.on_save = on_save

        self.title(f"计时器 {timer.index} 设置")
        self.configure(bg=C.BG)
        self.resizable(False, False)
        self.transient(app)
        self._build()
        self.grab_set()
        self.bind("<Escape>", lambda _e: self.destroy())

    def _build(self) -> None:
        hours, minutes, seconds = timers_mod.split_hms(self.timer.duration)
        lh, lm, ls = timers_mod.split_hms(self.timer.limit)

        self.title_var = tk.StringVar(value=self.timer.title)
        self.mode_var = tk.StringVar(value=self.timer.mode)
        self.hours_var = tk.StringVar(value=str(hours))
        self.minutes_var = tk.StringVar(value=str(minutes))
        self.seconds_var = tk.StringVar(value=str(seconds))
        self.lh_var = tk.StringVar(value=str(lh))
        self.lm_var = tk.StringVar(value=str(lm))
        self.ls_var = tk.StringVar(value=str(ls))
        self.reminder_var = tk.StringVar(value=self.timer.reminder)
        self.sound_var = tk.BooleanVar(value=self.timer.sound)

        outer = tk.Frame(self, bg=C.BG)
        outer.pack(fill="both", expand=True, padx=sp(20), pady=sp(18))

        head = tk.Frame(outer, bg=C.BG)
        head.pack(fill="x", pady=(0, sp(12)))
        label(head, f"计时器 {self.timer.index}", 13, C.TEXT, "bold", bg=C.BG).pack(
            side="left"
        )

        card = Card(outer)
        card.pack(fill="x")

        holder = form_row(card.body, "标题", "面板下方用它做设置按钮，也可单击序号显示")
        Input(holder, self.title_var).pack(fill="x")

        holder = form_row(card.body, "模式", "")
        Segmented(
            holder,
            [("up", "正计时"), ("down", "倒计时")],
            self.mode_var,
            bg=C.CARD,
        ).pack(anchor="w")

        self.mode_box = tk.Frame(card.body, bg=C.CARD)
        self.mode_box.pack(fill="x")

        footer = tk.Frame(outer, bg=C.BG)
        footer.pack(fill="x", pady=(sp(14), 0))
        FlatButton(footer, "保存", command=self._save, padx=22).pack(side="right")
        FlatButton(footer, "取消", command=self.destroy, kind="ghost").pack(
            side="right", padx=(0, sp(10))
        )

        self.mode_var.trace_add("write", lambda *_: self._render_mode())
        self._render_mode()

    def _render_mode(self) -> None:
        for child in self.mode_box.winfo_children():
            child.destroy()

        down = self.mode_var.get() == "down"
        if down:
            holder = form_row(
                self.mode_box,
                "倒计时时长",
                f"未开始时显示这个数字，最大 {timers_mod.format_hms(timers_mod.MAX_COUNT_SECONDS)}",
            )
            self._hms_row(holder, self.hours_var, self.minutes_var, self.seconds_var)

            holder = form_row(self.mode_box, "结束提醒文字", "倒数到 00:00:00 时弹出，可留空")
            Input(holder, self.reminder_var).pack(fill="x")

            row = tk.Frame(self.mode_box, bg=C.CARD)
            row.pack(fill="x", pady=(0, sp(12)))
            self._check(row, "声音报警（弹窗期间持续「滴」）", self.sound_var).pack(
                side="left"
            )
            return

        holder = form_row(
            self.mode_box,
            "计数上限",
            "可选；不填（0:0:0）则到 99:59:59 自动归零",
        )
        self._hms_row(holder, self.lh_var, self.lm_var, self.ls_var)
        label(
            self.mode_box,
            "到达上限后会立即从 00:00:00 重新开始计数。",
            8,
            C.TEXT_MUTED,
            bg=C.CARD,
        ).pack(anchor="w", pady=(0, sp(12)))

    def _hms_row(self, holder, hours_var, minutes_var, seconds_var) -> None:
        row = tk.Frame(holder, bg=C.CARD)
        row.pack(fill="x")
        for position, (var, unit) in enumerate(
            ((hours_var, "时"), (minutes_var, "分"), (seconds_var, "秒"))
        ):
            spinbox(
                row,
                from_=0,
                to=99 if position == 0 else 59,
                textvariable=var,
                width=4,
            ).pack(side="left")
            label(row, unit, 9, C.TEXT_DIM, bg=C.CARD).pack(
                side="left", padx=(sp(6), sp(10))
            )

    def _check(self, master, text: str, variable: tk.BooleanVar):
        return tk.Checkbutton(
            master,
            text=text,
            variable=variable,
            bg=C.CARD,
            fg=C.TEXT,
            activebackground=C.CARD,
            activeforeground=C.TEXT,
            selectcolor=C.BG,
            bd=0,
            highlightthickness=0,
            font=font(9),
            cursor="hand2",
            anchor="w",
        )

    def _int(self, var: tk.StringVar, default: int = 0) -> int:
        try:
            return max(0, int(str(var.get()).strip() or default))
        except ValueError:
            return default

    def _save(self) -> None:
        mode = self.mode_var.get()
        try:
            duration = timers_mod.parse_hms(
                parse_int(self.hours_var.get(), "小时", 0, 99),
                parse_int(self.minutes_var.get(), "分钟", 0, 59),
                parse_int(self.seconds_var.get(), "秒", 0, 59),
            )
            limit = timers_mod.parse_hms(
                parse_int(self.lh_var.get(), "上限小时", 0, 99),
                parse_int(self.lm_var.get(), "上限分钟", 0, 59),
                parse_int(self.ls_var.get(), "上限秒", 0, 59),
            )
        except InputError as exc:
            messagebox.showwarning("输入无效", str(exc), parent=self)
            return
        if mode == "down" and duration < 1:
            messagebox.showwarning("时长太短", "倒计时至少需要 1 秒。", parent=self)
            return
        if mode == "down":
            limit = 0
        title = self.title_var.get().strip() or f"计时器 {self.timer.index}"
        self.on_save(
            self.timer,
            title,
            mode,
            max(1, duration),
            limit,
            self.reminder_var.get().strip(),
            bool(self.sound_var.get()),
        )
        self.destroy()


class TimersPage(Page):
    title = "计时器"
    subtitle = "10 个独立计时器，点标题可修改设置"

    def _build(self) -> None:
        self.timers = timers_mod.load_timers(self.cfg.timers)
        self._cells: list[dict] = []
        self._set_buttons: list = []
        self._show_title = [False] * len(self.timers)

        outer = tk.Frame(self, bg=C.BG)
        outer.pack(fill="both", expand=True, padx=sp(26), pady=(0, sp(18)))

        panel = tk.Frame(
            outer, bg=INK, highlightbackground=C.BORDER, highlightthickness=1, bd=0
        )
        panel.pack(fill="x")
        for col in range(5):
            panel.grid_columnconfigure(col, weight=1, uniform="cell")
        for row in range(2):
            panel.grid_rowconfigure(row, weight=1, uniform="row", minsize=sp(131))

        for position, timer in enumerate(self.timers):
            row, col = divmod(position, 5)
            cell = tk.Frame(
                panel, bg=INK, highlightbackground=SEP_COLOR, highlightthickness=1
            )
            cell.grid(row=row, column=col, sticky="nsew")
            self._cells.append(self._build_cell(cell, timer))

        label(outer, ADVICE, 8, C.TEXT_MUTED, bg=C.BG).pack(
            anchor="w", pady=(sp(16), sp(8))
        )

        grid = tk.Frame(outer, bg=C.BG)
        grid.pack(fill="x")
        for col in range(5):
            grid.grid_columnconfigure(col, weight=1, uniform="set")

        for position, timer in enumerate(self.timers):
            row, col = divmod(position, 5)
            button = FlatButton(
                grid,
                "",
                command=lambda t=timer: self._open_settings(t),
                kind="secondary",
                padx=8,
                pady=9,
                font_size=9,
                bold=False,
            )
            button.grid(row=row, column=col, sticky="ew", padx=sp(4), pady=sp(4))
            self._set_buttons.append(button)

        self._apply_all()
        self.after(200, self._tick)

    def _build_cell(self, parent, timer: timers_mod.Timer) -> dict:
        index = tk.Label(
            parent,
            text=str(timer.index),
            bg=INK,
            fg=OFF_COLOR,
            font=INDEX_FONT,
            cursor="hand2",
        )
        index.bind("<Button-1>", lambda _e, t=timer: self._toggle_label(t))

        clock = tk.Label(parent, text="00:00:00", bg=INK, fg=OFF_COLOR, font=TIME_FONT)

        button = FlatButton(
            parent,
            "开始",
            command=lambda: self._toggle(timer),
            kind="secondary",
            padx=22,
            pady=5,
            font_size=9,
            bold=True,
        )

        widgets = {"index": index, "clock": clock, "button": button}
        parent.bind(
            "<Configure>",
            lambda _e, c=parent, w=widgets: self._layout_cell(c, w),
        )

        for widget in (parent, clock):
            widget.bind("<Double-1>", lambda _e, t=timer: self._open_settings(t))
            widget.bind("<Button-3>", lambda _e, t=timer: self._context_menu(t, widget))

        self._layout_cell(parent, widgets)
        return widgets

    def _layout_cell(self, cell, widgets: dict) -> None:
        """数字永远在格子正中；标题在上、按钮在下，且按钮离数字更近一点。"""
        height = cell.winfo_height()
        width = cell.winfo_width()
        if height <= 1 or width <= 1:
            return

        clock = widgets["clock"]
        index = widgets["index"]
        button = widgets["button"]

        try:
            number_h = clock.winfo_reqheight()
        except tk.TclError:
            return

        center = height // 2
        gap_title = max(sp(8), height // 14)
        gap_button = max(sp(5), height // 26)

        clock.place(relx=0.5, y=center, anchor="center")
        index.place(relx=0.5, y=center - number_h // 2 - gap_title, anchor="s")
        button.place(relx=0.5, y=center + number_h // 2 + gap_button, anchor="n")

    # ------------------------------------------------------------ 刷新
    def _row_color(self, timer: timers_mod.Timer) -> str:
        if timer.mode == timers_mod.MODE_DOWN:
            return DOWN_COLOR
        return ON_COLOR if timer.is_active else OFF_COLOR

    def _apply_row(self, timer: timers_mod.Timer) -> None:
        cell = self._cells[timer.index - 1]
        color = self._row_color(timer)

        if self._show_title[timer.index - 1]:
            cell["index"].configure(
                text=fit_text(self, timer.title, sp(200), size=11), font=TITLE_FONT
            )
        else:
            cell["index"].configure(text=str(timer.index), font=INDEX_FONT)
        # 序号始终白色，不随正/倒计时和运行状态变色
        cell["index"].configure(fg=OFF_COLOR)

        cell["clock"].configure(text=timer.display(), fg=color)
        cell["button"].configure(text=timer.button_text)
        cell["button"].set_kind("success" if timer.is_active else "secondary")

        self._set_buttons[timer.index - 1].configure(
            text=fit_text(self, timer.title, sp(230), size=9)
        )

    def _apply_all(self) -> None:
        for timer in self.timers:
            self._apply_row(timer)

    def _toggle_label(self, timer: timers_mod.Timer) -> None:
        position = timer.index - 1
        self._show_title[position] = not self._show_title[position]
        self._apply_row(timer)

    def _tick(self) -> None:
        if getattr(self.app, "_closed", False):
            return
        try:
            for timer in self.timers:
                finished = timer.tick()
                self._apply_row(timer)
                if finished:
                    self._announce(timer)
        except tk.TclError:
            return
        try:
            self.after(200, self._tick)
        except tk.TclError:
            pass

    def _announce(self, timer: timers_mod.Timer) -> None:
        text = timer.reminder.strip() or "计时结束，可以看一下时间安排。"
        self.app.status.set_message(f"计时结束：{timer.title}", "ok")
        try:
            TimerAlertDialog(self.app, timer.title, text, sound=timer.sound)
        except Exception:
            pass

    # ------------------------------------------------------------ 操作
    def _toggle(self, timer: timers_mod.Timer) -> None:
        if timer.status == timers_mod.STATUS_RUNNING:
            timer.stop()
            self.app.status.set_message(f"{timer.title} 已停止并归零", "warn")
        else:
            timer.start()
            self.app.status.set_message(f"{timer.title} 开始计时", "ok")
        self._apply_row(timer)

    def _reset(self, timer: timers_mod.Timer) -> None:
        timer.stop()
        self._apply_row(timer)

    def _reset_all(self) -> None:
        for timer in self.timers:
            timer.stop()
        self._apply_all()
        self.app.status.set_message("已归零全部计时器", "ok")

    def _context_menu(self, timer: timers_mod.Timer, widget) -> None:
        menu = tk.Menu(
            self,
            tearoff=0,
            bg=C.CARD,
            fg=C.TEXT,
            activebackground=C.ACCENT,
            activeforeground="#FFFFFF",
            bd=0,
            relief="flat",
            font=font(9),
        )
        menu.add_command(label="详细设置…", command=lambda: self._open_settings(timer))
        menu.add_command(label="归零", command=lambda: self._reset(timer))
        menu.add_separator()
        menu.add_command(label="全部归零", command=self._reset_all)
        try:
            menu.tk_popup(widget.winfo_rootx() + sp(30), widget.winfo_rooty() + sp(20))
        finally:
            menu.grab_release()

    def _open_settings(self, timer: timers_mod.Timer) -> None:
        dialog = TimerDialog(self.app, timer, self._on_saved)
        center_over(dialog, self.app)
        self.app.wait_window(dialog)

    def _on_saved(
        self,
        timer: timers_mod.Timer,
        title: str,
        mode: str,
        duration: int,
        limit: int,
        reminder: str,
        sound: bool,
    ) -> None:
        timer.apply(title, mode, duration, limit, reminder, sound)
        self.cfg.set_timers(timers_mod.dump_timers(self.timers))
        self._apply_row(timer)
        self.app.status.set_message(f"计时器 {timer.index} 设置已保存", "ok")

    def on_show(self) -> None:
        self._apply_all()
