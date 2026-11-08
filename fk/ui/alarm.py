"""时间闹钟页：倒计时提醒 / 指定时间提醒。"""
from __future__ import annotations

import tkinter as tk
from datetime import datetime, timedelta
from tkinter import messagebox

from .. import alarm as alarm_mod
from ..inpututils import InputError, parse_int
from ..theme import C, font, sp
from ..widgets import (
    Card,
    FlatButton,
    Input,
    ScrollFrame,
    Segmented,
    StatusDot,
    form_row,
    label,
    spinbox,
)
from .base import Page


def _repeat_hint(extra: dict) -> str:
    """确认框里显示重复规则。"""
    repeat = extra.get("repeat", "none")
    if repeat == "count":
        return f"循环提醒：总共 {extra.get('repeat_total', 2)} 次"
    if repeat == "forever":
        return "循环提醒：一直重复到手动停止"
    if repeat == "daily":
        return "间隔提醒：每天同一时间，手动停止为止"
    if repeat == "hourly":
        base = "间隔提醒：每个整点"
    elif repeat == "hour_min":
        base = (
            f"间隔提醒：每小时 {int(extra.get('minute', 0)):02d}:"
            f"{int(extra.get('second', 0)):02d}"
        )
    else:
        return "只提醒一次"
    if extra.get("window_enabled"):
        return f"{base}（{extra.get('window_start')}–{extra.get('window_end')}，手动停止为止）"
    return f"{base}（全天，手动停止为止）"


class ReminderDialog(tk.Toplevel):
    """到点后的确认弹窗（内容可以来自用户自定义文字）。"""

    def __init__(
        self,
        master,
        message: str,
        note: str = "",
        heading: str = "时间到了",
        window_title: str = "时间提醒",
    ):
        super().__init__(master)
        self.title(window_title)
        self.configure(bg=C.BG)
        self.resizable(False, False)
        try:
            self.attributes("-topmost", True)
        except tk.TclError:
            pass

        width, height = sp(500), sp(290)
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        self.geometry(
            f"{width}x{height}+{(screen_w - width) // 2}+{(screen_h - height) // 3}"
        )

        card = tk.Frame(
            self, bg=C.CARD, highlightbackground=C.BORDER, highlightthickness=1
        )
        card.pack(fill="both", expand=True, padx=sp(1), pady=sp(1))
        body = tk.Frame(card, bg=C.CARD)
        body.pack(fill="both", expand=True, padx=sp(24), pady=sp(20))

        head = tk.Frame(body, bg=C.CARD)
        head.pack(fill="x")
        StatusDot(head, C.AMBER, 12, bg=C.CARD).pack(side="left", padx=(0, sp(10)))
        label(head, heading, 15, C.TEXT, "bold", bg=C.CARD).pack(side="left")

        label(
            body,
            message or "设定的提醒时间到了。",
            12,
            C.TEXT,
            bg=C.CARD,
            wraplength=sp(430),
            justify="left",
        ).pack(anchor="w", pady=(sp(18), sp(8)))

        if note:
            label(body, note, 9, C.TEXT_MUTED, bg=C.CARD).pack(anchor="w")

        footer = tk.Frame(body, bg=C.CARD)
        footer.pack(fill="x", side="bottom", pady=(sp(16), 0))
        FlatButton(footer, "知道了", command=self.destroy, padx=26).pack(side="right")

        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda _e: self.destroy())
        try:
            self.bell()
        except tk.TclError:
            pass
        self.lift()
        try:
            self.focus_force()
        except tk.TclError:
            pass
        self._flash(0)

    def _flash(self, step: int) -> None:
        """闪两下标题栏区域，提醒注意。"""
        if step >= 4 or not self.winfo_exists():
            return
        color = C.ACCENT_SOFT if step % 2 == 0 else C.CARD
        try:
            self.configure(bg=color)
        except tk.TclError:
            return
        self.after(220, lambda: self._flash(step + 1))


class AlarmPage(Page):
    title = "时间闹钟"
    subtitle = "倒计时提醒或指定时刻提醒，到点响铃 / 弹窗"

    def _build(self) -> None:
        now = datetime.now()
        self._missed_notice_scheduled = False
        prefs = self.cfg.alarm_prefs or {}
        self.hours_var = tk.StringVar(value="0")
        self.minutes_var = tk.StringVar(value="10")
        self.seconds_var = tk.StringVar(value="0")
        self.date_var = tk.StringVar(value=now.strftime("%Y-%m-%d"))
        self.time_var = tk.StringVar(
            value=(now + timedelta(minutes=5)).strftime("%H:%M:%S")
        )
        self.sound_var = tk.BooleanVar(value=bool(prefs.get("sound", True)))
        self.dialog_var = tk.BooleanVar(value=bool(prefs.get("dialog", True)))
        self.text_var = tk.StringVar(value=str(prefs.get("text", "") or ""))

        self.repeat_var = tk.BooleanVar(value=False)
        self.repeat_mode_var = tk.StringVar(value="count")
        self.repeat_count_var = tk.StringVar(value="5")

        self.clock_repeat_var = tk.StringVar(value="none")
        self.hour_minute_var = tk.StringVar(value="0")
        self.hour_second_var = tk.StringVar(value="0")
        self.window_var = tk.BooleanVar(value=True)
        self.window_start_var = tk.StringVar(value="09:00")
        self.window_end_var = tk.StringVar(value="18:00")

        scroll = ScrollFrame(self, bg=C.BG)
        scroll.pack(fill="both", expand=True)
        wrap = tk.Frame(scroll.body, bg=C.BG)
        wrap.pack(fill="both", expand=True, padx=sp(26), pady=(sp(4), sp(26)))

        # ---------------- 当前状态
        card = Card(wrap)
        card.pack(fill="x", pady=(0, sp(14)))
        head = tk.Frame(card.body, bg=C.CARD)
        head.pack(fill="x")
        self.dot = StatusDot(head, C.TEXT_MUTED, 10, bg=C.CARD)
        self.dot.pack(side="left", padx=(0, sp(10)))
        self.status_text = label(head, "没有正在进行的提醒", 13, C.TEXT, "bold", bg=C.CARD)
        self.status_text.pack(side="left")
        self.cancel_btn = FlatButton(
            head, "取消提醒", command=self._cancel, kind="danger", padx=16, pady=6, font_size=9
        )
        self.cancel_btn.pack(side="right")

        self.countdown = label(
            card.body, "在下面设置倒计时或指定时间。", 9, C.TEXT_DIM, bg=C.CARD
        )
        self.countdown.pack(anchor="w", pady=(sp(10), 0))

        # ---------------- 倒计时
        card = Card(wrap)
        card.pack(fill="x", pady=(0, sp(14)))
        label(card.body, "倒计时提醒", 11, C.TEXT, "bold", bg=C.CARD).pack(
            anchor="w", pady=(0, sp(14))
        )
        row = tk.Frame(card.body, bg=C.CARD)
        row.pack(fill="x")
        label(row, "从现在起", 9, C.TEXT_DIM, bg=C.CARD).pack(side="left")
        spinbox(row, from_=0, to=99, textvariable=self.hours_var, width=4).pack(
            side="left", padx=sp(8)
        )
        label(row, "小时", 9, C.TEXT_DIM, bg=C.CARD).pack(side="left")
        spinbox(row, from_=0, to=59, textvariable=self.minutes_var, width=4).pack(
            side="left", padx=sp(8)
        )
        label(row, "分", 9, C.TEXT_DIM, bg=C.CARD).pack(side="left")
        spinbox(row, from_=0, to=59, textvariable=self.seconds_var, width=4).pack(
            side="left", padx=sp(8)
        )
        label(row, "秒后提醒", 9, C.TEXT_DIM, bg=C.CARD).pack(side="left")

        repeat_row = tk.Frame(card.body, bg=C.CARD)
        repeat_row.pack(fill="x", pady=(sp(12), 0))
        self._check(repeat_row, "循环提醒（到点后继续计时）", self.repeat_var).pack(side="left")

        self.repeat_box = tk.Frame(card.body, bg=C.CARD)
        self.repeat_box.pack(fill="x")

        self.start_button = FlatButton(
            card.body, "开始倒计时", command=self._start_countdown, padx=20, pady=8
        )
        self.start_button.pack(anchor="w", pady=(sp(14), 0))

        # ---------------- 指定时间
        card = Card(wrap)
        card.pack(fill="x", pady=(0, sp(14)))
        label(card.body, "指定时间提醒", 11, C.TEXT, "bold", bg=C.CARD).pack(
            anchor="w", pady=(0, sp(14))
        )

        holder = form_row(card.body, "日期", "格式 2026-10-24")
        Input(holder, self.date_var).pack(fill="x")

        holder = form_row(card.body, "时间", "24 小时制，可精确到秒")
        row = tk.Frame(holder, bg=C.CARD)
        row.pack(fill="x")
        self.time_input = Input(row, self.time_var)
        self.time_input.pack(side="left", fill="x", expand=True)
        label(row, "HH:MM:SS", 8, C.TEXT_MUTED, bg=C.CARD).pack(side="left", padx=(sp(10), 0))

        holder = form_row(card.body, "间隔提醒", "第一次响过之后按这个规则继续")
        Segmented(
            holder,
            [
                ("none", "不重复"),
                ("daily", "每天"),
                ("hourly", "每个整点"),
                ("hour_min", "每小时的第…"),
            ],
            self.clock_repeat_var,
            bg=C.CARD,
        ).pack(anchor="w")

        self.clock_repeat_box = tk.Frame(card.body, bg=C.CARD)
        self.clock_repeat_box.pack(fill="x")

        self.clock_button = FlatButton(
            card.body, "设定提醒", command=self._start_clock, padx=20, pady=8
        )
        self.clock_button.pack(anchor="w", pady=(sp(6), 0))

        # ---------------- 提醒方式
        card = Card(wrap)
        card.pack(fill="x", pady=(0, sp(14)))
        label(card.body, "提醒方式", 11, C.TEXT, "bold", bg=C.CARD).pack(
            anchor="w", pady=(0, sp(14))
        )
        sound_row = tk.Frame(card.body, bg=C.CARD)
        sound_row.pack(fill="x", pady=(0, sp(8)))
        self._check(sound_row, "播放两声短间隔的「滴」", self.sound_var).pack(side="left")
        FlatButton(
            sound_row,
            "试听",
            command=alarm_mod.play_double_beep,
            kind="subtle",
            padx=10,
            pady=4,
            font_size=8,
            bold=False,
        ).pack(side="left", padx=(sp(12), 0))

        self._check(card.body, "弹窗确认提醒（需要点「知道了」）", self.dialog_var).pack(
            anchor="w"
        )

        holder = form_row(card.body, "提醒文字", "弹窗里显示的内容，可留空")
        row = tk.Frame(holder, bg=C.CARD)
        row.pack(fill="x")
        text_input = Input(row, self.text_var)
        text_input.pack(side="left", fill="x", expand=True)
        FlatButton(
            row,
            "清空",
            command=lambda: self.text_var.set(""),
            kind="subtle",
            padx=10,
            pady=5,
            font_size=8,
            bold=False,
        ).pack(side="left", padx=(sp(8), 0))
        label(
            holder,
            "例如：该喝水了 / 会议 10 分钟后开始 / 记得保存文档",
            8,
            C.TEXT_MUTED,
            bg=C.CARD,
        ).pack(anchor="w", pady=(sp(6), 0))

        # ---------------- 说明
        card = Card(wrap)
        label(card.body, "说明", 11, C.TEXT, "bold", bg=C.CARD).pack(
            anchor="w", pady=(0, sp(12))
        )
        for line in (
            "提醒由本软件计时，需要电脑百宝箱保持运行（最小化到托盘也可以）。",
            "同一时间只保留一个提醒，重新设定会覆盖旧的。",
            "关闭软件后提醒会失效；重新打开时如果时间还没到，会继续计时。",
        ):
            label(
                card.body, "· " + line, 8, C.TEXT_MUTED, bg=C.CARD, justify="left", wraplength=sp(880)
            ).pack(anchor="w", pady=(0, sp(4)))

        self._refresh_status()
        self.repeat_var.trace_add("write", lambda *_: self._render_repeat())
        self.repeat_mode_var.trace_add("write", lambda *_: self._render_repeat())
        self.clock_repeat_var.trace_add("write", lambda *_: self._render_clock_repeat())
        self.window_var.trace_add("write", lambda *_: self._render_clock_repeat())
        self._render_repeat()
        self._render_clock_repeat()
        self.after(250, self._tick)

    # ------------------------------------------------------------ 重复设置
    @staticmethod
    def _reset_box(box, anchor=None) -> None:
        """清空内容。

        注意：Tk 在「子控件全部销毁」时不会收回容器高度，会留下空白，
        所以这里始终保留一个 1px 的占位条。
        """
        for child in box.winfo_children():
            child.destroy()
        tk.Frame(box, height=1, bg=C.CARD).pack(fill="x")

    def _render_repeat(self) -> None:
        self._reset_box(self.repeat_box)
        if not self.repeat_var.get():
            return

        Segmented(
            self.repeat_box,
            [("count", "总共提醒 N 次"), ("forever", "一直重复到手动停止")],
            self.repeat_mode_var,
            bg=C.CARD,
        ).pack(anchor="w", pady=(sp(10), sp(8)))

        if self.repeat_mode_var.get() == "count":
            row = tk.Frame(self.repeat_box, bg=C.CARD)
            row.pack(fill="x")
            label(row, "总共提醒", 9, C.TEXT_DIM, bg=C.CARD).pack(side="left")
            spinbox(row, from_=2, to=999, textvariable=self.repeat_count_var, width=5).pack(
                side="left", padx=sp(8)
            )
            label(row, "次（含第一次）", 9, C.TEXT_DIM, bg=C.CARD).pack(side="left")
        else:
            label(
                self.repeat_box,
                "会一直按同样的间隔重复，直到你点「取消提醒」。",
                8,
                C.TEXT_MUTED,
                bg=C.CARD,
            ).pack(anchor="w")

    def _time_picker(self, master, variable, width: int = 7):
        """Spinbox 传入 values 会重置文本，这里先存后还原。"""
        current = variable.get()
        widget = spinbox(
            master,
            values=[f"{h:02d}:{m:02d}" for h in range(24) for m in (0, 15, 30, 45)],
            textvariable=variable,
            width=width,
        )
        if current:
            variable.set(current)
        return widget

    def _render_clock_repeat(self) -> None:
        self._reset_box(self.clock_repeat_box)

        mode = self.clock_repeat_var.get()
        if mode in ("none", ""):
            return

        if mode == "daily":
            label(
                self.clock_repeat_box,
                "每天在同一时刻提醒，直到手动取消。",
                8,
                C.TEXT_MUTED,
                bg=C.CARD,
            ).pack(anchor="w", pady=(0, sp(8)))
            return

        if mode == "hour_min":
            row = tk.Frame(self.clock_repeat_box, bg=C.CARD)
            row.pack(fill="x", pady=(0, sp(8)))
            label(row, "每小时的", 9, C.TEXT_DIM, bg=C.CARD).pack(side="left")
            spinbox(row, from_=0, to=59, textvariable=self.hour_minute_var, width=4).pack(
                side="left", padx=sp(8)
            )
            label(row, "分", 9, C.TEXT_DIM, bg=C.CARD).pack(side="left")
            spinbox(row, from_=0, to=59, textvariable=self.hour_second_var, width=4).pack(
                side="left", padx=sp(8)
            )
            label(row, "秒提醒", 9, C.TEXT_DIM, bg=C.CARD).pack(side="left")

        win_row = tk.Frame(self.clock_repeat_box, bg=C.CARD)
        win_row.pack(fill="x", pady=(sp(4), sp(4)))
        self._check(win_row, "只在指定时间段内提醒", self.window_var).pack(side="left")

        detail = tk.Frame(self.clock_repeat_box, bg=C.CARD)
        detail.pack(fill="x")
        if not self.window_var.get():
            label(
                detail,
                "全天按间隔提醒，直到手动取消。",
                8,
                C.TEXT_MUTED,
                bg=C.CARD,
            ).pack(anchor="w")
            return

        label(detail, "从", 9, C.TEXT_DIM, bg=C.CARD).pack(side="left")
        self._time_picker(detail, self.window_start_var).pack(side="left", padx=sp(8))
        label(detail, "到", 9, C.TEXT_DIM, bg=C.CARD).pack(side="left")
        self._time_picker(detail, self.window_end_var).pack(side="left", padx=sp(8))
        label(detail, "每天（含起止时间）", 8, C.TEXT_MUTED, bg=C.CARD).pack(side="left")

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

    # ------------------------------------------------------------ 状态
    def _refresh_status(self) -> None:
        alarm = self.cfg.alarm
        if alarm and not alarm_mod.is_active(alarm):
            missed = alarm
            self.cfg.clear_alarm()
            alarm = None
            if not getattr(self, "_missed_notice_scheduled", False):
                self._missed_notice_scheduled = True
                try:
                    self.after(300, lambda item=missed: self._show_missed(item))
                except tk.TclError:
                    pass

        if not alarm:
            self.dot.set_color(C.TEXT_MUTED)
            self.status_text.configure(text="没有正在进行的提醒", fg=C.TEXT)
            self.countdown.configure(
                text="在下面设置倒计时或指定时间。", fg=C.TEXT_DIM
            )
            self.cancel_btn.set_enabled(False)
            return

        target = alarm_mod.alarm_target(alarm)
        if target is None:
            self.cfg.clear_alarm()
            self._refresh_status()
            return

        kind = "倒计时" if alarm.get("kind") == "countdown" else "指定时间"
        repeat_text = alarm_mod.repeat_label(alarm)
        title = f"{kind}提醒 · {alarm_mod.human_target(target)}"
        if repeat_text:
            title += f" · {repeat_text}"
        self.dot.set_color(C.ACCENT)
        self.status_text.configure(text=title, fg=C.ACCENT)
        self.cancel_btn.set_enabled(True)
        self._update_countdown()

    def _update_countdown(self) -> None:
        alarm = self.cfg.alarm
        target = alarm_mod.alarm_target(alarm) if alarm else None
        if target is None:
            return
        remaining = alarm_mod.seconds_left(target)
        label_text = str(alarm.get("label") or "").strip()
        text = f"剩余 {alarm_mod.human_hms(remaining)}    ·    {target.strftime('%Y-%m-%d %H:%M:%S')}"
        repeat_text = alarm_mod.repeat_label(alarm)
        if label_text:
            text += f"    ·    {label_text}"
        if repeat_text:
            text += f"    ·    {repeat_text}"
        self.countdown.configure(text=text, fg=C.TEXT_DIM)

    def _show_missed(self, alarm: dict) -> None:
        target = alarm_mod.alarm_target(alarm)
        when = target.strftime("%Y-%m-%d %H:%M:%S") if target else "设定时间"
        label_text = str(alarm.get("label") or "").strip()
        note = f"\n\n{label_text}" if label_text else ""
        messagebox.showinfo(
            "提醒已过期",
            f"这条提醒的时间（{when}）已经过去，软件当时没有运行，因此没有响铃。"
            f"{note}\n\n如需提醒，请在下方重新设定。",
            parent=self.app,
        )

    def _tick(self) -> None:
        if getattr(self.app, "_closed", False):
            return
        try:
            alarm = self.cfg.alarm
            if alarm:
                target = alarm_mod.alarm_target(alarm)
                if target is not None and datetime.now() >= target:
                    self._fire(alarm)
                else:
                    self._update_countdown()
        except tk.TclError:
            return
        try:
            self.after(250, self._tick)
        except tk.TclError:
            pass

    # ------------------------------------------------------------ 到点
    def _fire(self, alarm: dict) -> None:
        custom = str(alarm.get("text") or "").strip()
        message = custom or "设定的提醒时间到了。"
        label_text = str(alarm.get("label") or "").strip()
        when = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        note = f"{label_text}    ·    {when}" if label_text else when

        if alarm.get("sound", True):
            alarm_mod.play_double_beep()

        # 计算下一次；不重复就结束
        updated = alarm_mod.advance(alarm)
        if updated is not None:
            self.cfg.set_alarm(updated)
        else:
            self.cfg.clear_alarm()

        self._refresh_status()
        self.app.status.set_message(f"时间提醒：{message}", "warn")

        if alarm.get("dialog", True):
            ReminderDialog(self.app, message, note)

    # ------------------------------------------------------------ 动作
    def _int(self, var: tk.StringVar, default: int = 0) -> int:
        try:
            return max(0, int(str(var.get()).strip() or default))
        except ValueError:
            return default

    def _start_countdown(self) -> None:
        try:
            hours = parse_int(self.hours_var.get(), "小时", 0, 99)
            minutes = parse_int(self.minutes_var.get(), "分钟", 0, 59)
            seconds = parse_int(self.seconds_var.get(), "秒", 0, 59)
        except InputError as exc:
            messagebox.showwarning("输入无效", str(exc), parent=self.app)
            return
        total = hours * 3600 + minutes * 60 + seconds
        if total < 1:
            messagebox.showwarning("请填写时长", "倒计时至少 1 秒。", parent=self.app)
            return
        target = datetime.now() + timedelta(seconds=total)
        label_text = f"倒计时 {hours:02d}:{minutes:02d}:{seconds:02d}"

        repeat = "none"
        repeat_total = 1
        if self.repeat_var.get():
            if self.repeat_mode_var.get() == "count":
                try:
                    repeat_total = parse_int(
                        self.repeat_count_var.get(), "循环次数", 2, 9999
                    )
                except InputError as exc:
                    messagebox.showwarning("输入无效", str(exc), parent=self.app)
                    return
                repeat = "count"
            else:
                repeat = "forever"

        self._set_alarm(
            target,
            "countdown",
            label_text,
            interval_seconds=total,
            repeat=repeat,
            repeat_total=repeat_total,
        )

    def _start_clock(self) -> None:
        target = alarm_mod.parse_datetime(self.date_var.get(), self.time_var.get())
        if target is None:
            messagebox.showwarning(
                "格式不对",
                "日期请填 2026-10-24 这样的格式，时间用 08:30:00。",
                parent=self.app,
            )
            return
        if target <= datetime.now():
            messagebox.showwarning(
                "时间已经过去", "指定的时间早于现在，请换一个时间。", parent=self.app
            )
            return

        mode = self.clock_repeat_var.get()
        extra: dict = {"repeat": mode if mode in ("daily", "hourly", "hour_min") else "none"}
        if mode == "hour_min":
            try:
                extra["minute"] = parse_int(self.hour_minute_var.get(), "分钟", 0, 59)
                extra["second"] = parse_int(self.hour_second_var.get(), "秒", 0, 59)
            except InputError as exc:
                messagebox.showwarning("输入无效", str(exc), parent=self.app)
                return
        if mode in ("hourly", "hour_min"):
            extra["window_enabled"] = bool(self.window_var.get())
            extra["window_start"] = self.window_start_var.get()
            extra["window_end"] = self.window_end_var.get()

        self._set_alarm(
            target, "clock", f"提醒 · {target.strftime('%H:%M:%S')}", **extra
        )

    def _set_alarm(
        self,
        target: datetime,
        kind: str,
        label_text: str,
        confirm: bool = True,
        **extra,
    ) -> None:
        sound = bool(self.sound_var.get())
        dialog = bool(self.dialog_var.get())
        text = str(self.text_var.get()).strip()
        if not sound and not dialog:
            messagebox.showwarning(
                "请选择提醒方式",
                "至少要勾选「响铃」或「弹窗」中的一种，否则到点不会有任何提示。",
                parent=self.app,
            )
            return

        if confirm and not messagebox.askyesno(
            "确认提醒",
            f"将在 {alarm_mod.human_target(target)} 提醒你。\n"
            f"{_repeat_hint(extra)}\n"
            f"提醒方式：{' 响铃 ' if sound else ''}{' 弹窗 ' if dialog else ''}"
            f"{'　' + text if text else ''}\n\n确定吗？",
            parent=self.app,
        ):
            return

        self.cfg.set_alarm_prefs(sound, dialog, text)
        self.cfg.set_alarm(
            alarm_mod.make_alarm(target, kind, sound, dialog, label_text, text, **extra)
        )
        self._refresh_status()
        self.app.status.set_message(
            f"已设定提醒：{alarm_mod.human_target(target)}", "ok"
        )

    def quick_minutes(self, minutes: int) -> None:
        """托盘菜单用：直接倒计时 N 分钟，不弹确认框。"""
        prefs = self.cfg.alarm_prefs or {}
        sound = bool(prefs.get("sound", True))
        dialog = bool(prefs.get("dialog", True))
        text = str(prefs.get("text", "") or "")
        if not sound and not dialog:
            sound, dialog = True, True
        target = datetime.now() + timedelta(minutes=max(1, int(minutes)))
        self.cfg.set_alarm(
            alarm_mod.make_alarm(
                target, "countdown", f"倒计时 {minutes} 分钟", sound, dialog, text
            )
        )
        self._refresh_status()
        self.app.status.set_message(f"已设定 {minutes} 分钟倒计时提醒", "ok")

    def _cancel(self) -> None:
        self.cfg.clear_alarm()
        self._refresh_status()
        self.app.status.set_message("已取消提醒", "ok")

    def on_show(self) -> None:
        self._refresh_status()
