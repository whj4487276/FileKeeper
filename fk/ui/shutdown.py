"""定时关机页。"""
from __future__ import annotations

import tkinter as tk
from datetime import datetime, timedelta
from tkinter import messagebox

from .. import shutdown as shutdown_mod
from ..inpututils import InputError, parse_int
from ..theme import C, font, sp
from ..widgets import (
    Card,
    FlatButton,
    Input,
    ScrollFrame,
    Segmented,
    StatusDot,
    center_over,
    form_row,
    label,
    spinbox,
)
from .base import Page


class ExitShutdownDialog(tk.Toplevel):
    """退出时提示：还有未执行的关机计划，但不会修改它。"""

    CONTINUE = "continue"
    ABORT = "abort"
    # 兼容旧调用方
    CANCEL_AND_QUIT = CONTINUE
    KEEP_AND_QUIT = CONTINUE

    def __init__(self, app, plan: dict):
        super().__init__(app)
        self.app = app
        self.plan = plan or {}
        self.result = self.ABORT

        self.title("退出提示")
        self.configure(bg=C.BG)
        self.resizable(False, False)
        if app.is_visible():
            self.transient(app)

        outer = tk.Frame(self, bg=C.BG)
        outer.pack(fill="both", expand=True, padx=sp(22), pady=sp(20))

        head = tk.Frame(outer, bg=C.BG)
        head.pack(fill="x", pady=(0, sp(12)))
        StatusDot(head, C.AMBER, 12, bg=C.BG).pack(side="left", padx=(0, sp(10)))
        label(head, "还有未执行的关机计划", 14, C.TEXT, "bold", bg=C.BG).pack(side="left")

        card = Card(outer)
        card.pack(fill="x")
        for name, value in self._rows():
            row = tk.Frame(card.body, bg=C.CARD)
            row.pack(fill="x", pady=(0, sp(8)))
            label(row, name, 9, C.TEXT_DIM, bg=C.CARD, width=8, anchor="w").pack(side="left")
            label(row, value, 10, C.TEXT, bg=C.CARD, anchor="w").pack(side="left")

        label(
            outer,
            "退出软件不会取消这条计划，关机仍由 Windows 执行。\n"
            "点击「继续退出」不会对关机计划做任何修改。",
            9,
            C.AMBER,
            bg=C.BG,
            wraplength=sp(430),
            justify="left",
        ).pack(anchor="w", pady=(sp(12), sp(16)))

        footer = tk.Frame(outer, bg=C.BG)
        footer.pack(fill="x")
        FlatButton(
            footer,
            "继续退出",
            command=lambda: self._choose(self.CONTINUE),
            padx=20,
            pady=8,
        ).pack(side="right")
        FlatButton(
            footer,
            "取消退出",
            command=lambda: self._choose(self.ABORT),
            kind="secondary",
            padx=16,
            pady=8,
        ).pack(side="right", padx=(0, sp(10)))

        self.protocol("WM_DELETE_WINDOW", lambda: self._choose(self.ABORT))
        self.bind("<Escape>", lambda _e: self._choose(self.ABORT))
        self.grab_set()
        try:
            self.focus_force()
        except tk.TclError:
            pass

    def _rows(self) -> list[tuple[str, str]]:
        rows: list[tuple[str, str]] = []
        target = shutdown_mod.plan_target(self.plan)
        if target is not None:
            rows.append(
                (
                    "关机时间",
                    f"{shutdown_mod.human_target(target)}"
                    f"（{target.strftime('%Y-%m-%d %H:%M')}）",
                )
            )
            rows.append(
                (
                    "剩余时间",
                    shutdown_mod.human_countdown(shutdown_mod.seconds_until(target)),
                )
            )
        source = shutdown_mod.SOURCE_LABELS.get(str(self.plan.get("source", "")), "")
        if source:
            rows.append(("设定方式", source))
        if not rows:
            rows.append(("关机计划", "已设定"))
        return rows

    def _choose(self, result: str) -> None:
        self.result = result
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()


def ask_exit_with_shutdown(app) -> str:
    """弹出关机计划提示；返回 "continue" / "abort"。"""
    dialog = ExitShutdownDialog(app, app.config.shutdown_plan)
    center_over(dialog, app)
    try:
        app.wait_window(dialog)
    except tk.TclError:
        return dialog.result
    return dialog.result


class ShutdownPage(Page):
    title = "定时关机"
    subtitle = "按计划自动关机；关机由 Windows 执行，退出软件也依然有效"

    def _build(self) -> None:
        self.mode_var = tk.StringVar(value="delay")
        self.hours_var = tk.StringVar(value="10")
        self.minutes_var = tk.StringVar(value="0")
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        self.date_var = tk.StringVar(value=tomorrow)
        self.time_var = tk.StringVar(value="08:00")

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
        self.status_text = label(head, "未设置关机计划", 13, C.TEXT, "bold", bg=C.CARD)
        self.status_text.pack(side="left")
        self.cancel_btn = FlatButton(
            head, "取消关机", command=self._cancel, kind="danger", padx=16, pady=6, font_size=9
        )
        self.cancel_btn.pack(side="right")

        self.countdown = label(
            card.body, "在下面选择一个快捷方式，或自定义时间。", 9, C.TEXT_DIM, bg=C.CARD
        )
        self.countdown.pack(anchor="w", pady=(sp(10), 0))

        # ---------------- 快捷设置
        card = Card(wrap)
        card.pack(fill="x", pady=(0, sp(14)))
        label(card.body, "快捷设置", 11, C.TEXT, "bold", bg=C.CARD).pack(
            anchor="w", pady=(0, sp(14))
        )

        row = tk.Frame(card.body, bg=C.CARD)
        row.pack(fill="x")
        for text, command in (
            ("明天 08:00 关机", self._quick_tomorrow),
            ("今天 08:00 关机", self._quick_today),
            ("10 小时后关机", self._quick_hours10),
        ):
            FlatButton(
                row, text, command=command, kind="secondary", padx=16, pady=9, font_size=9
            ).pack(side="left", padx=(0, sp(10)))

        label(
            card.body,
            "「今天 08:00」如果已经过了，会自动改成明天 08:00。",
            8,
            C.TEXT_MUTED,
            bg=C.CARD,
        ).pack(anchor="w", pady=(sp(10), 0))

        # ---------------- 自定义
        card = Card(wrap)
        card.pack(fill="x", pady=(0, sp(14)))
        label(card.body, "自定义", 11, C.TEXT, "bold", bg=C.CARD).pack(
            anchor="w", pady=(0, sp(14))
        )

        holder = form_row(card.body, "方式", "")
        Segmented(
            holder,
            [("delay", "延时关机"), ("at", "指定时刻")],
            self.mode_var,
            bg=C.CARD,
        ).pack(anchor="w")

        self.mode_box = tk.Frame(card.body, bg=C.CARD)
        self.mode_box.pack(fill="x")

        actions = tk.Frame(card.body, bg=C.CARD)
        actions.pack(fill="x", pady=(sp(4), 0))
        FlatButton(actions, "设定关机", command=self._custom_apply, padx=22).pack(side="left")
        self.hint = label(
            actions,
            "",
            8,
            C.TEXT_MUTED,
            bg=C.CARD,
        )
        self.hint.pack(side="left", padx=(sp(12), 0))

        # ---------------- 说明
        card = Card(wrap)
        label(card.body, "使用说明", 11, C.TEXT, "bold", bg=C.CARD).pack(
            anchor="w", pady=(0, sp(12))
        )
        for line in (
            "关机由 Windows 自带功能执行，计划设定后即使退出电脑百宝箱也依然有效。",
            "重启发或注销会清除计划；重新开机后需要重新设定。",
            "关机前请保存正在编辑的文件，程序不会强制关闭未保存的文档。",
            "如果计划没生效，可以在这里点「取消关机」再重新设定。",
        ):
            label(card.body, "· " + line, 8, C.TEXT_MUTED, bg=C.CARD, justify="left", wraplength=sp(880)).pack(
                anchor="w", pady=(0, sp(4))
            )

        self.mode_var.trace_add("write", lambda *_: self._render_mode())
        self._render_mode()
        self._refresh_status()
        self.after(1000, self._tick)

    # ------------------------------------------------------------ 自定义区域
    def _render_mode(self) -> None:
        for child in self.mode_box.winfo_children():
            child.destroy()

        if self.mode_var.get() == "delay":
            row = tk.Frame(self.mode_box, bg=C.CARD)
            row.pack(fill="x", pady=(0, sp(14)))
            label(row, "在", 9, C.TEXT_DIM, bg=C.CARD).pack(side="left")
            spinbox(row, from_=0, to=999, textvariable=self.hours_var, width=5).pack(
                side="left", padx=sp(8)
            )
            label(row, "小时", 9, C.TEXT_DIM, bg=C.CARD).pack(side="left")
            spinbox(row, from_=0, to=59, textvariable=self.minutes_var, width=4).pack(
                side="left", padx=sp(8)
            )
            label(row, "分钟后关机", 9, C.TEXT_DIM, bg=C.CARD).pack(side="left")
            self.hint.configure(text="例如 10 小时 0 分钟")
            return

        holder = form_row(self.mode_box, "日期", "格式 2026-10-24")
        date_input = Input(holder, self.date_var)
        date_input.pack(fill="x")

        row = tk.Frame(self.mode_box, bg=C.CARD)
        row.pack(fill="x", pady=(0, sp(14)))
        label(row, "时间", 9, C.TEXT_DIM, bg=C.CARD).pack(side="left")
        # Spinbox 传入 values 会把文本重置为第一项，这里先存后还原
        current_time = self.time_var.get()
        picker = spinbox(
            row,
            values=[f"{h:02d}:{m:02d}" for h in range(24) for m in (0, 15, 30, 45)],
            textvariable=self.time_var,
            width=7,
        )
        picker.pack(side="left", padx=sp(8))
        if current_time:
            self.time_var.set(current_time)
        label(row, "（24 小时制）", 8, C.TEXT_MUTED, bg=C.CARD).pack(side="left")
        self.hint.configure(text="到了这个日期和时间就关机")

    # ------------------------------------------------------------ 状态刷新
    def _refresh_status(self) -> None:
        plan = self.cfg.shutdown_plan
        if plan and not shutdown_mod.plan_is_alive(plan):
            self.cfg.clear_shutdown()
            plan = None

        if not plan:
            self.dot.set_color(C.TEXT_MUTED)
            self.status_text.configure(text="未设置关机计划", fg=C.TEXT)
            self.countdown.configure(
                text="在下面选择一个快捷方式，或自定义时间。",
                fg=C.TEXT_DIM,
            )
            self.cancel_btn.set_enabled(False)
            return

        target = shutdown_mod.plan_target(plan)
        if target is None:
            self.cfg.clear_shutdown()
            self._refresh_status()
            return

        self.dot.set_color(C.AMBER)
        self.status_text.configure(
            text=f"将在 {shutdown_mod.human_target(target)} 关机",
            fg=C.AMBER,
        )
        self.cancel_btn.set_enabled(True)
        self._update_countdown()

    def _update_countdown(self) -> None:
        plan = self.cfg.shutdown_plan
        target = shutdown_mod.plan_target(plan) if plan else None
        if target is None:
            return
        remaining = shutdown_mod.seconds_until(target)
        if not shutdown_mod.plan_is_alive(plan):
            self.countdown.configure(text="计划已失效（可能重启过电脑），请重新设定。", fg=C.RED)
            return
        text = (
            f"剩余 {shutdown_mod.human_countdown(remaining)}"
            f"    ·    {target.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        self.countdown.configure(text=text, fg=C.TEXT_DIM)

    def _tick(self) -> None:
        if getattr(self.app, "_closed", False):
            return
        try:
            self._update_countdown()
        except tk.TclError:
            return
        try:
            self.after(1000, self._tick)
        except tk.TclError:
            pass

    # ------------------------------------------------------------ 动作
    def _arm(self, target: datetime, source: str, confirm: bool = True) -> None:
        pretty = target.strftime("%Y-%m-%d %H:%M")
        existing = shutdown_mod.plan_is_alive(self.cfg.shutdown_plan)
        if confirm and not messagebox.askyesno(
            "确认关机计划",
            f"将安排在 {shutdown_mod.human_target(target)}（{pretty}）关闭计算机。\n\n"
            "关机前请保存正在编辑的文件。"
            + ("\n\n这会替换当前已设置的关机计划。" if existing else "")
            + "\n\n确定吗？",
            parent=self.app,
        ):
            return

        ok, error = shutdown_mod.arm(
            target,
            comment=f"电脑百宝箱：{pretty} 关机",
            replace_existing=existing,
        )
        if not ok:
            if confirm:
                messagebox.showerror(
                    "无法设定关机",
                    f"{error or '系统拒绝了关机请求。'}\n\n"
                    "如果系统已有其他关机计划，请先在「定时关机」页取消它。",
                    parent=self.app,
                )
            else:
                self.app.status.set_message(f"设定关机失败：{error}", "error")
            return

        self.cfg.set_shutdown(shutdown_mod.make_plan(target, source))
        self._refresh_status()
        self.app.status.set_message(f"已安排在 {pretty} 关机", "ok")

    def quick(self, source: str, confirm: bool = True) -> None:
        """托盘菜单用：按快捷方式设定关机。"""
        if source == "tomorrow8":
            self._arm(shutdown_mod.tomorrow_at(8, 0), "tomorrow8", confirm)
        elif source == "today8":
            target, rolled = shutdown_mod.today_at(8, 0)
            if rolled and confirm:
                self.app.status.set_message(
                    "今天 08:00 已经过了，已自动改为明天 08:00", "warn"
                )
            self._arm(target, "today8", confirm)
        elif source == "hours10":
            self._arm(shutdown_mod.after_delay(10, 0), "hours10", confirm)

    def _quick_tomorrow(self) -> None:
        self.quick("tomorrow8")

    def _quick_today(self) -> None:
        self.quick("today8")

    def _quick_hours10(self) -> None:
        self.quick("hours10")

    def _int(self, var: tk.StringVar, default: int = 0) -> int:
        try:
            return max(0, int(str(var.get()).strip() or default))
        except ValueError:
            return default

    def _custom_apply(self) -> None:
        if self.mode_var.get() == "delay":
            try:
                hours = parse_int(self.hours_var.get(), "延时小时", 0, 100000)
                minutes = parse_int(self.minutes_var.get(), "延时分钟", 0, 59)
            except InputError as exc:
                messagebox.showwarning("输入无效", str(exc), parent=self.app)
                return
            if hours == 0 and minutes == 0:
                messagebox.showwarning(
                    "请填写时长", "延时至少要 1 分钟。", parent=self.app
                )
                return
            target = shutdown_mod.after_delay(hours, minutes)
            self._arm(target, "custom_delay")
            return

        target = shutdown_mod.parse_datetime(self.date_var.get(), self.time_var.get())
        if target is None:
            messagebox.showwarning(
                "格式不对",
                "日期请填 2026-10-24 这样的格式，时间用 08:00。",
                parent=self.app,
            )
            return
        if target <= datetime.now():
            messagebox.showwarning(
                "时间已经过去", "指定的时间早于现在，请换一个时间。", parent=self.app
            )
            return
        self._arm(target, "custom_time")

    def _cancel(self) -> None:
        ok, error = shutdown_mod.cancel()
        self.cfg.clear_shutdown()
        self._refresh_status()
        if ok:
            self.app.status.set_message("已取消关机计划", "ok")
        else:
            messagebox.showwarning(
                "取消可能未生效",
                f"{error}\n\n建议在 Windows 命令行执行 shutdown /a 确认。",
                parent=self.app,
            )

    # ------------------------------------------------------------ 页面事件
    def on_show(self) -> None:
        self._refresh_status()
