"""快速截图：区域选择 + 简单标注编辑。"""
from __future__ import annotations

import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

from .. import annotate as ann
from .. import capture as cap_mod
from .. import hotkey as hk
from ..hotkeys import (
    ACTION_BY_ID,
    ACTIONS,
    MAX_GLOBAL_HOTKEYS,
    STATUS_ACTIVE,
    STATUS_FAILED,
    STATUS_UNSET,
    is_admin,
    validate_binding,
)
from ..paths import pictures_dir
from ..saveutils import (
    NETWORK_SAVE_TIMEOUT,
    SAVE_GATE,
    SaveError,
    check_directory,
    check_target_file,
    is_network_path,
    normalize_save_path,
    save_in_progress,
    save_png_atomic,
    suggest_default_name,
)
from ..theme import C, font, sp
from ..widgets import (
    Card,
    FlatButton,
    ScrollFrame,
    Segmented,
    center_over,
    label,
    spinbox,
)
from .base import Page

SELECT_COLOR = "#FF3B30"

PALETTE = [
    ("红", (255, 59, 48)),
    ("黄", (255, 212, 0)),
    ("蓝", (47, 123, 255)),
    ("绿", (52, 199, 89)),
    ("紫", (175, 82, 222)),
    ("黑", (0, 0, 0)),
    ("白", (255, 255, 255)),
    ("灰", (142, 142, 147)),
]

TOOLS = [
    ("rect", "矩形"),
    ("ellipse", "椭圆"),
    ("arrow", "箭头"),
]


def color_hex(color: tuple[int, int, int]) -> str:
    return f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}"


class CaptureOverlay(tk.Toplevel):
    """全屏遮罩：拖拽框选，双击确认，Esc / 右键取消。"""

    def __init__(self, app, on_done, on_cancel, screen=None):
        super().__init__(app)
        self.app = app
        self._on_done = on_done
        self._on_cancel = on_cancel
        self._start: tuple[float, float] | None = None
        self._dragged = False
        self._rect_item = None
        self._selection: tuple[int, int, int, int] | None = None

        # 先把整块屏幕抓下来，确认时直接裁剪，避免"关掉遮罩后屏幕还没刷新"导致画面发暗
        self._screen = screen
        if self._screen is None:
            try:
                self._screen = cap_mod.grab_screen(*cap_mod.virtual_screen())
            except Exception:
                self._screen = None

        self.overrideredirect(True)
        self.configure(bg="#000000")
        try:
            self.attributes("-topmost", True)
            self.attributes("-alpha", 0.32)
        except tk.TclError:
            pass

        origin_x, origin_y, vw, vh = cap_mod.virtual_screen()
        self._origin = (origin_x, origin_y)
        self.geometry(f"{vw}x{vh}+{origin_x}+{origin_y}")

        self.canvas = tk.Canvas(
            self, bg="#000000", highlightthickness=0, bd=0, cursor="crosshair"
        )
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<Double-Button-1>", self._confirm)
        self.canvas.bind("<Button-3>", lambda _e: self._cancel())
        self.bind("<Escape>", lambda _e: self._cancel())

        self.update()
        try:
            self.focus_force()
            self.grab_set()
        except tk.TclError:
            pass

    # ------------------------------------------------------------ 选区
    def _press(self, event) -> None:
        self._start = (self.canvas.canvasx(event.x), self.canvas.canvasy(event.y))
        self._dragged = False

    def _drag(self, event) -> None:
        if self._start is None:
            return
        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)
        if not self._dragged:
            if abs(x - self._start[0]) < 3 and abs(y - self._start[1]) < 3:
                return
            self._dragged = True
            self.canvas.delete("hint")
        if self._rect_item is None:
            self._rect_item = self.canvas.create_rectangle(
                self._start[0], self._start[1], x, y, outline=SELECT_COLOR, width=2
            )
        else:
            self.canvas.coords(self._rect_item, self._start[0], self._start[1], x, y)

    def _release(self, event) -> None:
        if self._start is None:
            return
        start = self._start
        self._start = None
        if not self._dragged:
            return

        x = int(self.canvas.canvasx(event.x))
        y = int(self.canvas.canvasy(event.y))
        left, right = sorted((int(start[0]), x))
        top, bottom = sorted((int(start[1]), y))
        if right - left < 4 or bottom - top < 4:
            return

        ox, oy = self._origin
        self._selection = (left + ox, top + oy, right + ox, bottom + oy)
        if self._rect_item is not None:
            self.canvas.coords(self._rect_item, left, top, right, bottom)
        self._show_hint(left, top, right, bottom)

    def _show_hint(self, left: int, top: int, right: int, bottom: int) -> None:
        self.canvas.delete("hint")
        text = f"{right - left} × {bottom - top}　双击确认 · Esc 取消"
        text_y = bottom + sp(18) if bottom + sp(40) < self.winfo_height() else top - sp(18)
        item = self.canvas.create_text(
            (left + right) / 2,
            text_y,
            text=text,
            fill="#FFFFFF",
            font=font(10, "bold"),
            tags="hint",
        )
        box = self.canvas.bbox(item)
        if box:
            self.canvas.create_rectangle(
                box[0] - sp(8),
                box[1] - sp(4),
                box[2] + sp(8),
                box[3] + sp(4),
                fill="#000000",
                outline="",
                tags="hint",
            )
            self.canvas.tag_raise(item)

    # ------------------------------------------------------------ 结束
    def _confirm(self, _event=None) -> None:
        if not self._selection:
            return
        left, top, right, bottom = self._selection
        origin_x, origin_y = self._origin
        screen = self._screen
        self._close()

        if screen is not None:
            # 从开拍前抓好的整屏图里裁，像素绝对干净
            image = cap_mod.crop(
                screen, left - origin_x, top - origin_y, right - left, bottom - top
            )
        else:
            try:
                self.app.update()
            except tk.TclError:
                pass
            time.sleep(0.12)
            image = cap_mod.grab_screen(left, top, right - left, bottom - top)

        if image is None:
            self._on_cancel("截图失败：无法读取屏幕内容")
        else:
            self._on_done(image)

    def _cancel(self) -> None:
        self._close()
        self._on_cancel(None)

    def _close(self) -> None:
        try:
            self.grab_release()
        except tk.TclError:
            pass
        try:
            self.destroy()
        except tk.TclError:
            pass


class HotkeyDialog(tk.Toplevel):
    """录制一个快捷键；Esc 取消，Backspace/Delete 清除。"""

    def __init__(self, app, action_label: str, modifiers: int, vk: int, on_save):
        super().__init__(app)
        self.app = app
        self.on_save = on_save
        self._mods = int(modifiers or 0)
        self._vk = int(vk or 0)
        self._held = 0
        self._complete = False
        self.title(f"设置快捷键 · {action_label}")
        self.configure(bg=C.BG)
        self.resizable(False, False)
        if app.is_visible():
            self.transient(app)

        body = tk.Frame(self, bg=C.BG)
        body.pack(fill="both", expand=True, padx=sp(26), pady=sp(22))
        label(body, f"为「{action_label}」录制快捷键", 13, C.TEXT, "bold", bg=C.BG).pack(
            anchor="w"
        )
        label(
            body,
            "按下组合键；修饰键顺序不限。Esc 取消，Backspace / Delete 清除绑定。",
            9,
            C.TEXT_DIM,
            bg=C.BG,
        ).pack(anchor="w", pady=(sp(6), sp(14)))

        self.display = label(body, "", 16, C.ACCENT, "bold", bg=C.BG)
        self.display.pack(anchor="w", pady=(0, sp(8)))
        self.error = label(body, "", 9, C.RED, bg=C.BG, wraplength=sp(380), justify="left")
        self.error.pack(anchor="w", pady=(0, sp(12)))

        footer = tk.Frame(body, bg=C.BG)
        footer.pack(fill="x")
        FlatButton(footer, "取消", command=self._cancel, kind="ghost").pack(side="right")
        FlatButton(footer, "保存", command=self._save, padx=20).pack(
            side="right", padx=(0, sp(10))
        )
        FlatButton(footer, "清除", command=self._clear, kind="subtle", font_size=9).pack(
            side="right", padx=(0, sp(10))
        )

        self.bind("<KeyPress>", self._on_key)
        self.bind("<KeyRelease>", self._on_key_release)
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self._render()
        self.update_idletasks()
        center_over(self, app)
        self.grab_set()
        try:
            self.focus_force()
        except tk.TclError:
            pass

    def _render(self) -> None:
        if self._vk:
            self.display.configure(
                text=hk.format_hotkey(self._mods, self._vk, spaced=True)
            )
        else:
            self.display.configure(text="未设置（保存后禁用）")

    def _set_error(self, text: str) -> None:
        self.error.configure(text=text)

    def _clear(self) -> None:
        self._mods = 0
        self._vk = 0
        self._held = 0
        self._complete = False
        self._set_error("已清空；保存后该功能将变为禁用。")
        self._render()

    def _on_key(self, event):
        keysym = event.keysym
        if keysym == "Escape":
            self._cancel()
            return "break"
        if keysym in ("BackSpace", "Delete"):
            self._clear()
            return "break"

        bit = hk.modifier_bit(keysym)
        if bit:
            self._held |= bit
            if self._vk:
                self._mods |= bit
                self._complete = bool(self._mods and self._vk)
                self._render()
            return "break"

        if self._complete:
            # 只响应首次完整组合，避免录制过程中被后续按键改掉
            return "break"

        vk = hk.keysym_to_vk(keysym)
        if vk is None:
            self._set_error("不支持这个主键，请使用字母、数字、F 键、方向键或编辑键。")
            return "break"
        self._mods = (self._held | hk.modifiers_from_state(event.state)) & hk.ALL_MODIFIERS
        self._vk = vk
        self._complete = bool(self._mods and self._vk)
        self._set_error("")
        self._render()
        return "break"

    def _on_key_release(self, event):
        bit = hk.modifier_bit(event.keysym)
        if bit:
            self._held &= ~bit
            return "break"
        return None

    def _save(self) -> None:
        if not self._vk:
            if self._held or self._mods:
                self._set_error("组合还没完成：请再按一个主键；按 Backspace 可清空。")
                return
            ok, message = self.on_save(0, 0)
            if ok:
                self.destroy()
            else:
                self._set_error(message or "保存失败")
                self._regrab()
            return

        error = validate_binding(self._mods, self._vk)
        if error:
            self._set_error(error)
            return
        ok, message = self.on_save(self._mods, self._vk)
        if ok:
            self.destroy()
        else:
            self._set_error(message or "保存失败，原快捷键保持不变")
            self._regrab()

    def _regrab(self) -> None:
        try:
            self.grab_set()
            self.focus_force()
        except tk.TclError:
            pass

    def _cancel(self) -> None:
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()


class ReplaceHotkeyDialog(tk.Toplevel):
    """内部冲突：取消 / 替换（解除对方绑定）。"""

    def __init__(self, parent, message: str):
        super().__init__(parent)
        self.result = False
        self.title("快捷键冲突")
        self.configure(bg=C.BG)
        self.resizable(False, False)
        try:
            self.transient(parent)
        except tk.TclError:
            pass
        body = tk.Frame(self, bg=C.BG)
        body.pack(fill="both", expand=True, padx=sp(24), pady=sp(20))
        label(body, "这个快捷键已经被使用", 12, C.TEXT, "bold", bg=C.BG).pack(anchor="w")
        label(body, message, 9, C.TEXT_DIM, bg=C.BG, wraplength=sp(360), justify="left").pack(
            anchor="w", pady=(sp(8), sp(18))
        )
        footer = tk.Frame(body, bg=C.BG)
        footer.pack(fill="x")
        FlatButton(footer, "取消", command=self._cancel, kind="ghost").pack(side="right")
        FlatButton(footer, "替换", command=self._replace, kind="danger", padx=18).pack(
            side="right", padx=(0, sp(10))
        )
        self.update_idletasks()
        try:
            center_over(self, parent)
            self.grab_set()
            self.focus_force()
        except tk.TclError:
            pass
        self.bind("<Escape>", lambda _event: self._cancel())

    def _replace(self) -> None:
        self.result = True
        self.destroy()

    def _cancel(self) -> None:
        self.result = False
        self.destroy()


class ShotEditor(tk.Toplevel):
    """截图编辑窗口。"""

    def __init__(self, app, image: cap_mod.RawImage):
        super().__init__(app)
        self.app = app
        self.image = image
        self.shapes: list[dict] = []
        self.tool = "rect"
        self.color: tuple[int, int, int] = PALETTE[0][1]
        self.line_width = 3
        self._start: tuple[float, float] | None = None
        self._drawing = False
        self._saving = False
        self._gate_held = False
        self._save_async = False
        self._save_thread: threading.Thread | None = None
        self._save_cancel = threading.Event()
        self._save_result: dict | None = None
        self._save_path: Path | None = None
        self._save_started = 0.0

        self.title(f"快速截图 · {image.width}×{image.height}")
        self.configure(bg=C.BG)
        # 主窗口藏在托盘时不能设 transient，否则这个窗口会跟着一起被隐藏
        if app.is_visible():
            self.transient(app)
        self._build()
        self._place_window()
        self.bind("<Destroy>", self._on_destroy, add="+")
        self.after(80, self._bring_to_front)

    def _bring_to_front(self) -> None:
        try:
            self.lift()
            self.focus_force()
        except tk.TclError:
            pass

    def _build(self) -> None:
        bar = tk.Frame(self, bg=C.CARD, height=sp(50))
        bar.pack(fill="x")
        bar.pack_propagate(False)
        self._bar = bar

        inner = tk.Frame(bar, bg=C.CARD)
        inner.pack(fill="x", padx=sp(14), pady=sp(9))
        self._inner = inner

        label(inner, "工具", 9, C.TEXT_DIM, bg=C.CARD).pack(side="left", padx=(0, sp(8)))

        self.tool_var = tk.StringVar(value=self.tool)
        Segmented(inner, TOOLS, self.tool_var, bg=C.CARD).pack(side="left")
        self.tool_var.trace_add("write", lambda *_: self._set_tool(self.tool_var.get()))

        label(inner, "颜色", 9, C.TEXT_DIM, bg=C.CARD).pack(side="left", padx=(sp(18), sp(8)))
        self._chips: list[tuple[tk.Frame, tuple[int, int, int]]] = []
        for _name, rgb in PALETTE:
            chip = tk.Frame(
                inner,
                bg=color_hex(rgb),
                width=sp(21),
                height=sp(21),
                cursor="hand2",
                highlightthickness=2,
                highlightbackground=C.CARD,
            )
            chip.pack(side="left", padx=sp(3))
            chip.pack_propagate(False)
            chip.bind("<Button-1>", lambda _e, c=rgb: self._set_color(c))
            self._chips.append((chip, rgb))

        label(inner, "粗细", 9, C.TEXT_DIM, bg=C.CARD).pack(side="left", padx=(sp(18), sp(8)))
        self.width_var = tk.StringVar(value=str(self.line_width))
        spinbox(inner, from_=1, to=16, textvariable=self.width_var, width=3).pack(side="left")
        self.width_var.trace_add("write", lambda *_: self._set_width())

        self.save_button = FlatButton(
            inner, "保存截图 (Ctrl+S)", command=self.save, padx=18, pady=7
        )
        self.save_button.pack(side="right")
        self._set_color(self.color)

        holder = tk.Frame(self, bg="#0B0B0B")
        holder.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(
            holder, bg="#0B0B0B", highlightthickness=0, bd=0, cursor="crosshair"
        )
        vbar = tk.Scrollbar(holder, orient="vertical", command=self.canvas.yview)
        hbar = tk.Scrollbar(holder, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=vbar.set, xscrollcommand=hbar.set)
        vbar.pack(side="right", fill="y")
        hbar.pack(side="bottom", fill="x")
        self.canvas.pack(side="left", fill="both", expand=True)

        # 累积渲染结果：每画一个形状就画在这张图上，预览和保存完全一致
        self.display_image = self.image.copy()
        self._photo_data = cap_mod.png_data_uri(self.display_image)
        self.photo = tk.PhotoImage(data=self._photo_data)
        self._image_item = self.canvas.create_image(0, 0, anchor="nw", image=self.photo)
        self.canvas.configure(scrollregion=(0, 0, self.image.width, self.image.height))

        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.bind("<Control-s>", self.save)
        self.bind("<Control-S>", self.save)
        self.bind("<Escape>", lambda _e: self.destroy())

    def _place_window(self) -> None:
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        self.update_idletasks()
        try:
            need_w = max(
                self.image.width + sp(6), self._inner.winfo_reqwidth() + sp(36)
            )
        except tk.TclError:
            need_w = self.image.width + sp(6)
        width = min(need_w, int(screen_w * 0.9))
        height = min(self.image.height + sp(120), int(screen_h * 0.86))
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 3)
        self.geometry(f"{width}x{height}+{x}+{y}")

    # ------------------------------------------------------------ 工具栏
    def _set_tool(self, tool: str) -> None:
        if tool in ("rect", "ellipse", "arrow"):
            self.tool = tool

    def _set_color(self, color: tuple[int, int, int]) -> None:
        self.color = color
        for chip, rgb in getattr(self, "_chips", []):
            chip.configure(
                highlightbackground=C.ACCENT if rgb == color else C.CARD,
            )

    def _set_width(self) -> None:
        try:
            value = int(str(self.width_var.get()).strip() or 3)
        except ValueError:
            return
        self.line_width = max(1, min(16, value))

    # ------------------------------------------------------------ 画图
    def _press(self, event) -> None:
        self._start = (self.canvas.canvasx(event.x), self.canvas.canvasy(event.y))
        self._drawing = False

    def _drag(self, event) -> None:
        if self._start is None:
            return
        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)
        if not self._drawing:
            if abs(x - self._start[0]) < 2 and abs(y - self._start[1]) < 2:
                return
            self._drawing = True
        self.canvas.delete("preview")
        self._paint(self._start[0], self._start[1], x, y, tags="preview")

    def _release(self, event) -> None:
        if self._start is None or not self._drawing:
            self._start = None
            self._drawing = False
            return
        end_x = self.canvas.canvasx(event.x)
        end_y = self.canvas.canvasy(event.y)
        start_x, start_y = self._start
        self._start = None
        self._drawing = False
        self.canvas.delete("preview")

        shape = {
            "kind": self.tool,
            "x1": int(start_x),
            "y1": int(start_y),
            "x2": int(end_x),
            "y2": int(end_y),
            "color": self.color,
            "width": self.line_width,
        }
        self.shapes.append(shape)
        # 直接画进累积图再刷新显示，这样预览就是最终保存的效果（带抗锯齿）
        ann.apply_shape(self.display_image, shape)
        self._refresh_image()

    def _refresh_image(self) -> None:
        try:
            self._photo_data = cap_mod.png_data_uri(self.display_image)
            self.photo = tk.PhotoImage(data=self._photo_data)
            self.canvas.itemconfigure(self._image_item, image=self.photo)
        except tk.TclError:
            pass

    def _paint(self, x1, y1, x2, y2, tags=None, shape: dict | None = None) -> None:
        shape = shape or {
            "kind": self.tool,
            "color": self.color,
            "width": self.line_width,
        }
        color = color_hex(shape["color"])
        width = int(shape.get("width", 3))
        kind = shape["kind"]

        if kind == "rect":
            self.canvas.create_rectangle(
                x1, y1, x2, y2, outline=color, width=width, tags=tags
            )
        elif kind == "ellipse":
            self.canvas.create_oval(x1, y1, x2, y2, outline=color, width=width, tags=tags)
        else:
            tip, left, right = ann.head_points(x1, y1, x2, y2, width)
            base_x = (left[0] + right[0]) / 2.0
            base_y = (left[1] + right[1]) / 2.0
            self.canvas.create_line(
                x1,
                y1,
                base_x * 0.45 + tip[0] * 0.55,
                base_y * 0.45 + tip[1] * 0.55,
                fill=color,
                width=width,
                tags=tags,
            )
            self.canvas.create_polygon(
                tip[0],
                tip[1],
                left[0],
                left[1],
                right[0],
                right[1],
                fill=color,
                outline=color,
                tags=tags,
            )

    # ------------------------------------------------------------ 保存
    def _on_destroy(self, event=None) -> None:
        if event is not None and event.widget is not self:
            return
        self._save_cancel.set()
        if self._gate_held:
            SAVE_GATE.release()
            self._gate_held = False
        self._saving = False
        self._save_async = False

    def _set_saving_ui(self, active: bool) -> None:
        try:
            self.save_button.set_enabled(not active)
            self.save_button.configure(
                text="正在保存…" if active else "保存截图 (Ctrl+S)"
            )
        except tk.TclError:
            pass

    def _release_save(self) -> None:
        if self._gate_held:
            SAVE_GATE.release()
            self._gate_held = False
        self._saving = False
        self._save_async = False
        self._save_thread = None
        self._set_saving_ui(False)

    def _initial_save_dir(self) -> str:
        prefs = dict(self.app.config.screenshot_prefs or {})
        last_dir = str(prefs.get("last_dir") or "").strip()
        if last_dir:
            if is_network_path(last_dir):
                if self._directory_available(last_dir):
                    return last_dir
            else:
                try:
                    if Path(last_dir).is_dir():
                        return last_dir
                except OSError:
                    pass
            self.app.status.set_message(
                "上次保存目录不可用，已回退到系统图片目录", "info"
            )
        return str(pictures_dir())

    @staticmethod
    def _directory_available(path: str, timeout: float = 0.6) -> bool:
        """网络目录快速探测：超时按不可用处理，避免保存对话框卡住。"""
        result: dict[str, bool] = {}
        event = threading.Event()

        def probe() -> None:
            try:
                result["ok"] = Path(path).is_dir()
            except OSError:
                result["ok"] = False
            finally:
                event.set()

        threading.Thread(target=probe, daemon=True).start()
        if not event.wait(timeout):
            return False
        return bool(result.get("ok"))

    def save(self, _event=None):
        if self._saving:
            return "break"
        if not SAVE_GATE.acquire():
            messagebox.showinfo(
                "正在保存",
                "已有截图正在保存，请稍候再试。",
                parent=self,
            )
            return "break"
        self._saving = True
        self._gate_held = True
        self._save_async = False
        self._save_cancel.clear()
        self._set_saving_ui(True)
        try:
            self._save_with_dialog()
        except Exception as exc:  # noqa: BLE001
            self._save_async = False
            messagebox.showerror("保存失败", f"保存过程中出现异常：\n{exc}", parent=self)
        finally:
            if not self._save_async:
                self._release_save()
        return "break"

    def _save_with_dialog(self) -> None:
        initial_dir = self._initial_save_dir()
        initial_name = suggest_default_name()
        while True:
            selected = filedialog.asksaveasfilename(
                parent=self,
                title="保存截图",
                initialdir=initial_dir,
                initialfile=initial_name,
                defaultextension=".png",
                filetypes=[("PNG 图片", "*.png")],
            )
            if not selected:
                return

            path, notes, error = normalize_save_path(selected)
            if error or path is None:
                messagebox.showerror("文件名不合法", error or "请重新输入文件名", parent=self)
                initial_dir = str(Path(selected).parent)
                initial_name = Path(selected).name
                continue
            if notes:
                messagebox.showinfo("文件名已调整", "\n".join(notes), parent=self)

            if is_network_path(path):
                self._start_async_save(path)
                return

            problem = check_directory(path) or check_target_file(path)
            if problem:
                messagebox.showerror("无法保存", problem, parent=self)
                initial_dir = str(path.parent)
                initial_name = path.name
                continue

            try:
                save_png_atomic(path, self.display_image)
            except SaveError as exc:
                messagebox.showerror("保存失败", exc.message, parent=self)
                initial_dir = str(path.parent)
                initial_name = path.name
                continue

            self._commit_saved(path)
            return

    def _start_async_save(self, path: Path) -> None:
        self._save_path = Path(path)
        self._save_result = None
        self._save_started = time.monotonic()
        self._save_async = True
        snapshot = self.display_image.copy()
        target = str(path)

        def work() -> None:
            result = {"ok": False, "message": "保存失败"}
            try:
                if self._save_cancel.is_set():
                    raise SaveError("保存已取消")
                problem = check_directory(target) or check_target_file(target)
                if problem:
                    raise SaveError(problem)
                if self._save_cancel.is_set():
                    raise SaveError("保存已取消")
                save_png_atomic(
                    target, snapshot, cancel_check=self._save_cancel.is_set
                )
                result = {"ok": True, "message": ""}
            except SaveError as exc:
                result = {"ok": False, "message": exc.message}
            except Exception as exc:  # noqa: BLE001
                result = {"ok": False, "message": f"写入失败：{exc}"}
            finally:
                self._save_result = result

        self.app.status.set_message("正在保存到网络位置…", "info")
        self._save_thread = threading.Thread(
            target=work, name="fk-shot-save", daemon=True
        )
        try:
            self._save_thread.start()
        except Exception:
            self._save_async = False
            self._release_save()
            raise
        try:
            self.after(100, self._poll_async_save)
        except tk.TclError:
            self._save_cancel.set()
            self._release_save()

    def _poll_async_save(self) -> None:
        if not self.winfo_exists() or not self._save_async:
            return
        thread = self._save_thread
        if thread is not None and thread.is_alive():
            if time.monotonic() - self._save_started > NETWORK_SAVE_TIMEOUT:
                self._save_cancel.set()
                self.app.status.set_message(
                    "网络位置保存超时，正在等待后台写入结束…", "warn"
                )
                messagebox.showerror(
                    "保存超时",
                    f"网络位置超过 {NETWORK_SAVE_TIMEOUT:.0f} 秒没有响应，保存已取消。\n\n"
                    "请重新选择一个本机文件夹。",
                    parent=self,
                )
                self._wait_abandoned_save()
                return
            self.after(100, self._poll_async_save)
            return

        result = self._save_result or {"ok": False, "message": "保存失败"}
        path = self._save_path
        self._release_save()
        if result.get("ok") and path is not None:
            self._commit_saved(path)
            return
        self.app.status.set_message(
            f"保存失败：{result.get('message') or '请更换目录'}", "warn"
        )
        messagebox.showerror(
            "保存失败",
            str(result.get("message") or "保存失败"),
            parent=self,
        )
        self._reselect_later()

    def _wait_abandoned_save(self) -> None:
        thread = self._save_thread
        if thread is not None and thread.is_alive() and self.winfo_exists():
            self.after(100, self._wait_abandoned_save)
            return
        self._release_save()
        self._reselect_later()

    def _reselect_later(self) -> None:
        try:
            self.after(150, self.save)
        except tk.TclError:
            pass

    def _commit_saved(self, path: Path) -> None:
        saved = Path(path)
        try:
            self.app.config.set_screenshot_prefs(last_dir=str(saved.parent))
        except Exception:
            pass
        self.app.status.set_message(f"截图已保存：{saved}", "ok")
        return "break"


class ShotPage(Page):
    title = "快速截图"
    subtitle = "区域 / 全屏 / 窗口截图，快捷键全部可自定义"

    def _build(self) -> None:
        self._overlay = None
        self._capturing = False
        self._hidden_windows: list[tk.Toplevel] = []
        self._was_visible = False
        self._rows: dict[str, dict] = {}
        self._capture_buttons: dict[str, FlatButton] = {}

        scroll = ScrollFrame(self, bg=C.BG)
        scroll.pack(fill="both", expand=True)

        outer = tk.Frame(scroll.body, bg=C.BG)
        outer.pack(fill="both", expand=True, padx=sp(26), pady=(0, sp(26)))

        card = Card(outer)
        card.pack(fill="x")

        row = tk.Frame(card.body, bg=C.CARD)
        row.pack(fill="x")
        for action in ACTIONS:
            button = FlatButton(
                row,
                action.label,
                command=lambda action_id=action.id: self.start_action(action_id),
                padx=18,
                pady=10,
                font_size=9,
            )
            button.pack(side="left", padx=(0, sp(8)))
            self._capture_buttons[action.id] = button

        label(
            card.body,
            "区域截图：拖选后双击确认；全屏 / 窗口截图：立即截取当前屏幕或前台窗口。"
            "　快捷键注册失败时，仍可用这里的按钮或托盘菜单截图。",
            9,
            C.TEXT_DIM,
            bg=C.CARD,
            wraplength=sp(980),
            justify="left",
        ).pack(anchor="w", pady=(sp(12), 0))

        self.warning_frame = tk.Frame(
            outer,
            bg=C.RED_SOFT,
            highlightthickness=1,
            highlightbackground=C.RED,
            bd=0,
        )
        self.warning_label = label(
            self.warning_frame,
            "",
            9,
            C.RED,
            bg=C.RED_SOFT,
            wraplength=sp(940),
            justify="left",
        )
        self.warning_label.pack(anchor="w", padx=sp(14), pady=sp(10))

        hotkeys = Card(outer)
        hotkeys.pack(fill="x", pady=(sp(14), 0))
        self.hotkey_card = hotkeys

        head = tk.Frame(hotkeys.body, bg=C.CARD)
        head.pack(fill="x", pady=(0, sp(10)))
        label(head, "快捷键", 11, C.TEXT, "bold", bg=C.CARD).pack(side="left")
        self.count_label = label(head, "", 9, C.TEXT_DIM, bg=C.CARD)
        self.count_label.pack(side="right")

        grid = tk.Frame(hotkeys.body, bg=C.CARD)
        grid.pack(fill="x")
        grid.grid_columnconfigure(0, weight=1)

        for index, action in enumerate(ACTIONS):
            line = index * 3
            name = label(grid, action.label, 10, C.TEXT, "bold", bg=C.CARD)
            name.grid(row=line, column=0, sticky="w", pady=(0, sp(2)))
            label(
                grid,
                action.description,
                8,
                C.TEXT_MUTED,
                bg=C.CARD,
            ).grid(row=line + 1, column=0, sticky="w", pady=(0, sp(10)))

            binding = label(grid, "", 11, C.ACCENT, "bold", bg=C.CARD)
            binding.grid(row=line, column=1, rowspan=2, sticky="w", padx=(sp(18), sp(18)))

            status = label(grid, "", 8, C.TEXT_DIM, bg=C.CARD, wraplength=sp(210))
            status.grid(row=line, column=2, rowspan=2, sticky="w", padx=(0, sp(14)))

            buttons = tk.Frame(grid, bg=C.CARD)
            buttons.grid(row=line, column=3, rowspan=2, sticky="e")
            toggle = FlatButton(
                buttons,
                "已禁用",
                command=lambda action_id=action.id: self._toggle(action_id),
                kind="ghost",
                padx=10,
                pady=4,
                font_size=8,
                bold=False,
            )
            toggle.pack(side="left")
            FlatButton(
                buttons,
                "修改",
                command=lambda action_id=action.id: self._edit(action_id),
                kind="secondary",
                padx=11,
                pady=4,
                font_size=8,
                bold=False,
            ).pack(side="left", padx=(sp(6), 0))
            FlatButton(
                buttons,
                "恢复默认",
                command=lambda action_id=action.id: self._reset(action_id),
                kind="ghost",
                padx=9,
                pady=4,
                font_size=8,
                bold=False,
            ).pack(side="left", padx=(sp(4), 0))

            self._rows[action.id] = {
                "name": name,
                "binding": binding,
                "status": status,
                "toggle": toggle,
            }

            if index != len(ACTIONS) - 1:
                tk.Frame(grid, bg=C.BORDER_SOFT, height=1).grid(
                    row=line + 2,
                    column=0,
                    columnspan=4,
                    sticky="ew",
                    pady=(0, sp(10)),
                )

        footer = tk.Frame(hotkeys.body, bg=C.CARD)
        footer.pack(fill="x", pady=(sp(14), 0))
        FlatButton(
            footer, "全部重新注册", command=self._retry_all, kind="secondary", font_size=9
        ).pack(side="left")
        FlatButton(
            footer, "导出…", command=self._export, kind="ghost", font_size=9
        ).pack(side="left", padx=(sp(8), 0))
        FlatButton(
            footer, "导入…", command=self._import, kind="ghost", font_size=9
        ).pack(side="left", padx=(sp(4), 0))
        self.import_status = label(footer, "", 8, C.TEXT_MUTED, bg=C.CARD)
        self.import_status.pack(side="left", padx=(sp(10), 0))

        label(
            hotkeys.body,
            f"最多 {MAX_GLOBAL_HOTKEYS} 个全局热键；禁用状态不占用注册名额。"
            "录制时按 Esc 取消、Backspace / Delete 清除；保存失败会保留原绑定。",
            8,
            C.TEXT_MUTED,
            bg=C.CARD,
            wraplength=sp(960),
            justify="left",
        ).pack(anchor="w", pady=(sp(12), 0))
        if not is_admin():
            label(
                hotkeys.body,
                "提示：当前以普通权限运行。对以管理员权限打开的窗口，全局热键可能无效；"
                "如需覆盖这类窗口，请以管理员身份运行本软件。",
                8,
                C.AMBER,
                bg=C.CARD,
                wraplength=sp(960),
                justify="left",
            ).pack(anchor="w", pady=(sp(6), 0))

        tips = Card(outer)
        tips.pack(fill="x", pady=(sp(14), 0))
        label(tips.body, "操作提示", 11, C.TEXT, "bold", bg=C.CARD).pack(
            anchor="w", pady=(0, sp(8))
        )
        for text in (
            "区域截图：按住左键拖选，松开后双击框内确认；Esc 或右键取消。",
            "全屏截图使用虚拟屏幕坐标，多显示器和非 100% 缩放都会按物理像素抓取。",
            "窗口截图截取前台窗口；触发时本软件窗口会先隐藏再截屏，不会把自己截进去。",
            "编辑窗口支持矩形 / 椭圆 / 箭头、8 种颜色、粗细 1–16，按 Ctrl+S 保存 PNG。",
        ):
            label(
                tips.body,
                "· " + text,
                9,
                C.TEXT_MUTED,
                bg=C.CARD,
                wraplength=sp(980),
                justify="left",
            ).pack(anchor="w", pady=(0, sp(5)))

        self.refresh_hotkeys()

    # ------------------------------------------------------------ 截图动作
    def start_capture(self) -> None:
        self.start_action("capture.region")

    def start_action(self, action_id: str) -> None:
        if self._capturing:
            return
        if save_in_progress():
            self.app.status.set_message("正在保存截图，请稍候再截图…", "warn")
            return
        if self.app.grab_current() is not None:
            # 录制/弹窗等模态框打开时不抢焦点
            return
        if action_id not in ACTION_BY_ID:
            return
        self._capturing = True
        self._was_visible = self.app.is_visible()
        if self._was_visible:
            self.app.hide_window()
        self._hidden_windows = [
            window
            for window in self.app.winfo_children()
            if isinstance(window, tk.Toplevel)
            and window.winfo_exists()
            and window.winfo_ismapped()
        ]
        for window in self._hidden_windows:
            try:
                window.withdraw()
            except tk.TclError:
                pass
        delay = 180 if action_id == "capture.region" else (
            220 if action_id == "capture.window" else 150
        )
        self.app.after(delay, lambda: self._do_capture(action_id))

    def _do_capture(self, action_id: str) -> None:
        if action_id == "capture.region":
            self._open_overlay()
            return
        try:
            if action_id == "capture.fullscreen":
                image = cap_mod.grab_fullscreen()
                size_text = "全屏"
            else:
                image, bounds = cap_mod.grab_active_window()
                size_text = (
                    f"窗口 {bounds[2]}×{bounds[3]}" if bounds else "窗口截图"
                )
        except Exception as exc:  # noqa: BLE001
            self._cancel(f"截图失败：{exc}")
            return
        if image is None:
            self._cancel("截图失败：无法读取屏幕内容")
            return
        self._finish(image, size_text)

    def _open_overlay(self) -> None:
        try:
            self._overlay = CaptureOverlay(
                self.app,
                on_done=self._finish,
                on_cancel=lambda message: self._cancel(message or ""),
            )
        except Exception as exc:  # noqa: BLE001
            self._cancel(f"无法启动截图：{exc}")

    def _restore_windows(self) -> None:
        for window in self._hidden_windows:
            try:
                if window.winfo_exists():
                    window.deiconify()
            except tk.TclError:
                pass
        self._hidden_windows = []
        if self._was_visible:
            self.app.show_window()
        self._was_visible = False

    def _finish(self, image, size_text: str = "") -> None:
        self._overlay = None
        self._capturing = False
        self._restore_windows()
        try:
            ShotEditor(self.app, image)
        except Exception as exc:  # noqa: BLE001
            self.app.status.set_message(f"打开编辑窗口失败：{exc}", "error")
            return
        detail = f"（{size_text}）" if size_text else ""
        self.app.status.set_message(
            f"已截取 {image.width}×{image.height}{detail}", "ok"
        )

    def _cancel(self, message: str | None = None) -> None:
        self._overlay = None
        self._capturing = False
        self._restore_windows()
        if message:
            self.app.status.set_message(message, "warn")

    # ------------------------------------------------------------ 快捷键
    def _registry(self):
        return getattr(self.app, "hotkey_registry", None)

    def refresh_hotkeys(self) -> None:
        registry = self._registry()
        if registry is None:
            for action in ACTIONS:
                row = self._rows.get(action.id)
                if not row:
                    continue
                row["binding"].configure(text="—")
                row["status"].configure(text="热键不可用", fg=C.RED)
                row["toggle"].configure(text="—", state="disabled")
                self._capture_buttons[action.id].configure(
                    text=f"{action.label}"
                )
            self.count_label.configure(text=f"0 / {MAX_GLOBAL_HOTKEYS}")
            self._show_warning(["全局热键不可用：系统托盘未启动。"])
            return

        failures = []
        for action in ACTIONS:
            row = self._rows[action.id]
            binding = registry.binding(action.id)
            state = registry.state(action.id)
            text = binding.text or "未设置"
            row["binding"].configure(text=text)
            if state.status == STATUS_ACTIVE:
                if state.error:
                    row["status"].configure(
                        text="仍用旧键（新键注册失败）", fg=C.AMBER
                    )
                else:
                    row["status"].configure(text="已注册", fg=C.GREEN)
                row["name"].configure(fg=C.TEXT)
                row["toggle"].configure(text="停用", state="normal")
                row["toggle"].set_kind("success")
                suffix = ""
            elif state.status == STATUS_FAILED:
                row["status"].configure(
                    text="注册失败：可能被占用", fg=C.RED
                )
                row["name"].configure(fg=C.RED)
                row["toggle"].configure(
                    text="停用" if binding.enabled else "启用", state="normal"
                )
                row["toggle"].set_kind("danger")
                suffix = "（不可用）"
                failures.append(f"「{action.label}」{state.error or '注册失败'}")
            elif state.status == STATUS_UNSET:
                row["status"].configure(text="未设置", fg=C.TEXT_DIM)
                row["name"].configure(fg=C.TEXT)
                row["toggle"].configure(text="启用", state="normal")
                row["toggle"].set_kind("ghost")
                suffix = "（无快捷键）"
            else:
                row["status"].configure(text="已禁用", fg=C.TEXT_MUTED)
                row["name"].configure(fg=C.TEXT)
                row["toggle"].configure(text="启用", state="normal")
                row["toggle"].set_kind("ghost")
                suffix = "（无快捷键）" if not binding.vk else "（已禁用）"

            self._capture_buttons[action.id].configure(
                text=f"{action.label}  {text}{suffix}"
            )

        self.count_label.configure(
            text=f"已启用 {registry.enabled_count()} / {MAX_GLOBAL_HOTKEYS}"
        )
        self._show_warning(failures)

    def _show_warning(self, messages: list[str]) -> None:
        if not messages:
            try:
                self.warning_frame.pack_forget()
            except tk.TclError:
                pass
            return
        extra = ""
        if any("区域截图" in item for item in messages):
            extra = "\n仍可通过上方按钮或托盘菜单「截图」启动。"
        self.warning_label.configure(text="\n".join(messages) + extra)
        if not self.warning_frame.winfo_ismapped():
            self.warning_frame.pack(
                fill="x", pady=(sp(12), 0), before=self.hotkey_card
            )

    def _toggle(self, action_id: str) -> None:
        registry = self._registry()
        if registry is None:
            return
        binding = registry.binding(action_id)
        if binding.enabled:
            result = self.app.set_hotkey_enabled(action_id, False)
        elif not binding.configured:
            self._edit(action_id)
            return
        else:
            result = self.app.set_hotkey_enabled(action_id, True)
        if result.conflict_action:
            other = ACTION_BY_ID.get(result.conflict_action)
            parent = self.app.grab_current() or self.app
            dialog = ReplaceHotkeyDialog(
                parent,
                f"该快捷键已用于「{other.label if other else result.conflict_action}」。\n"
                "选择“替换”会解除对方的绑定，只保留当前功能。",
            )
            self.app.wait_window(dialog)
            if not dialog.result:
                self.message("已取消，原快捷键保持不变", "warn")
                return
            result = self.app.apply_hotkey(
                action_id,
                binding.modifiers,
                binding.vk,
                enabled=True,
                replace=True,
            )
        self._report(action_id, result)

    def _edit(self, action_id: str) -> None:
        registry = self._registry()
        if registry is None:
            return
        binding = registry.binding(action_id)
        action = ACTION_BY_ID[action_id]
        dialog = HotkeyDialog(
            self.app,
            action.label,
            binding.modifiers,
            binding.vk,
            lambda modifiers, vk: self._save_binding(action_id, modifiers, vk),
        )
        self.app.wait_window(dialog)

    def _save_binding(self, action_id: str, modifiers: int, vk: int) -> tuple[bool, str]:
        if not modifiers and not vk:
            result = self.app.apply_hotkey(action_id, 0, 0, enabled=False)
            if result.ok:
                self.message("快捷键已清除", "ok")
                return True, ""
            return False, result.error

        result = self.app.apply_hotkey(action_id, modifiers, vk, enabled=True)
        if result.conflict_action:
            other = ACTION_BY_ID.get(result.conflict_action)
            parent = self.app.grab_current() or self.app
            dialog = ReplaceHotkeyDialog(
                parent,
                f"该快捷键已用于「{other.label if other else result.conflict_action}」。\n"
                "选择“替换”会解除对方的绑定，只保留当前功能。",
            )
            self.app.wait_window(dialog)
            if not dialog.result:
                return False, "已取消，原快捷键保持不变"
            result = self.app.apply_hotkey(
                action_id, modifiers, vk, enabled=True, replace=True
            )

        if result.ok:
            self.message(
                f"「{ACTION_BY_ID[action_id].label}」快捷键已更新", "ok"
            )
            return True, ""
        return False, result.error

    def _reset(self, action_id: str) -> None:
        action = ACTION_BY_ID[action_id]
        if action.default_vk:
            ok, message = self._save_binding(
                action_id, action.default_modifiers, action.default_vk
            )
            if not ok:
                self.message(
                    f"「{action.label}」恢复默认失败：{message or '请稍后重试'}",
                    "error",
                )
            return
        result = self.app.reset_hotkey(action_id)
        self._report(action_id, result)

    def _retry_all(self) -> None:
        failures = self.app.retry_hotkeys()
        if failures:
            self.message(f"仍有 {len(failures)} 个快捷键注册失败", "warn")
        else:
            self.message("所有已启用的快捷键都已注册", "ok")

    def _report(self, action_id: str, result) -> None:
        action = ACTION_BY_ID[action_id]
        if result.ok:
            self.message(f"「{action.label}」设置已保存", "ok")
        else:
            self.message(f"「{action.label}」：{result.error}", "error")

    def _export(self) -> None:
        path = self.app.export_hotkeys()
        if path:
            self.import_status.configure(text=f"已导出到 {path}")

    def _import(self) -> None:
        ok, message = self.app.import_hotkeys()
        self.import_status.configure(text=message[:80])
        self.message(message, "ok" if ok else "warn")

    def on_show(self) -> None:
        self.refresh_hotkeys()
