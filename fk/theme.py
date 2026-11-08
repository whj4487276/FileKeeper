"""配色、字体、DPI 缩放与 ttk 样式。"""
from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk


class C:
    BG = "#101218"
    BG_DEEP = "#0B0D12"
    SIDEBAR = "#14171E"
    SIDEBAR_HOVER = "#1C212B"
    CARD = "#1A1E26"
    CARD_ALT = "#212734"
    CARD_HOVER = "#272E3C"
    BORDER = "#2A3140"
    BORDER_SOFT = "#232936"

    TEXT = "#E8EBF2"
    TEXT_DIM = "#9AA5B8"
    TEXT_MUTED = "#6B7488"
    TEXT_INV = "#0E1116"

    ACCENT = "#4C8DFF"
    ACCENT_HOVER = "#6BA3FF"
    ACCENT_SOFT = "#1D2C49"
    ACCENT_LINE = "#2F4C82"

    GREEN = "#3ECF8E"
    GREEN_SOFT = "#15322A"
    AMBER = "#F5B544"
    AMBER_SOFT = "#33291A"
    RED = "#F26B76"
    RED_SOFT = "#3A2126"


UI_FAMILY = "Microsoft YaHei UI"
FALLBACK_FAMILY = "Segoe UI"
MONO_FAMILY = "Consolas"

SCALE = 1.0
_state: dict = {"family": UI_FAMILY, "dpi": 96.0}


def sp(value: float) -> int:
    """把「逻辑像素」换算成当前 DPI 下的实际像素。"""
    return int(round(value * SCALE))


def family() -> str:
    return _state["family"]


def font(size: int = 10, weight: str = "normal", family_name: str | None = None):
    return (family_name or _state["family"], size, weight)


def mono(size: int = 10):
    return (MONO_FAMILY, size, "normal")


def _default_font(root: tk.Misc) -> str:
    try:
        base = tkfont.Font(root=root, family=_state["family"], size=10)
        _state["default_font"] = base
        return base.name
    except Exception:
        return "TkDefaultFont"


def setup(root: tk.Misc) -> None:
    """解析字体、计算缩放比例并配置 ttk 样式。"""
    global SCALE

    try:
        families = set(tkfont.families(root))
    except Exception:
        families = set()
    if UI_FAMILY in families:
        _state["family"] = UI_FAMILY
    elif FALLBACK_FAMILY in families:
        _state["family"] = FALLBACK_FAMILY

    try:
        dpi = float(root.winfo_fpixels("1i"))
    except Exception:
        dpi = 96.0
    if dpi <= 0:
        dpi = 96.0
    _state["dpi"] = dpi
    SCALE = max(1.0, min(2.5, dpi / 96.0))

    try:
        root.tk.call("tk", "scaling", dpi / 72.0)
    except Exception:
        pass

    root.option_add("*Font", _default_font(root))
    root.option_add("*TCombobox*Listbox.background", C.CARD_ALT)
    root.option_add("*TCombobox*Listbox.foreground", C.TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", C.ACCENT)
    root.option_add("*TCombobox*Listbox.selectForeground", "#FFFFFF")
    root.option_add("*TCombobox*Listbox.borderWidth", 0)

    _style(root)


def _style(root: tk.Misc) -> None:
    st = ttk.Style(root)
    try:
        st.theme_use("clam")
    except tk.TclError:
        pass

    st.configure(
        ".",
        background=C.BG,
        foreground=C.TEXT,
        fieldbackground=C.CARD,
        bordercolor=C.BORDER,
        focuscolor=C.BG,
        troughcolor=C.CARD,
        selectbackground=C.ACCENT_SOFT,
        selectforeground=C.TEXT,
    )
    st.configure("TFrame", background=C.BG)
    st.configure("Card.TFrame", background=C.CARD)
    st.configure("TLabel", background=C.BG, foreground=C.TEXT)
    st.configure("Dim.TLabel", background=C.BG, foreground=C.TEXT_DIM)

    for name, orient in (
        ("Vertical.TScrollbar", "vertical"),
        ("Horizontal.TScrollbar", "horizontal"),
    ):
        st.configure(
            name,
            background=C.CARD_ALT,
            troughcolor=C.BG,
            bordercolor=C.BG,
            darkcolor=C.CARD_ALT,
            lightcolor=C.CARD_ALT,
            arrowcolor=C.TEXT_MUTED,
            relief="flat",
            borderwidth=0,
            gripcount=0,
            arrowsize=sp(10),
        )
        st.map(
            name,
            background=[("active", C.CARD_HOVER), ("pressed", C.ACCENT)],
            arrowcolor=[("active", C.TEXT_DIM)],
            lightcolor=[("active", C.CARD_HOVER)],
            darkcolor=[("active", C.CARD_HOVER)],
        )
    st.configure("Vertical.TScrollbar", width=sp(10))
    st.configure("Horizontal.TScrollbar", width=sp(10))

    st.configure(
        "Bar.Horizontal.TProgressbar",
        troughcolor=C.CARD,
        background=C.ACCENT,
        bordercolor=C.CARD,
        lightcolor=C.ACCENT,
        darkcolor=C.ACCENT,
        thickness=sp(6),
        borderwidth=0,
    )
    st.configure(
        "Green.Horizontal.TProgressbar",
        troughcolor=C.CARD,
        background=C.GREEN,
        bordercolor=C.CARD,
        lightcolor=C.GREEN,
        darkcolor=C.GREEN,
        thickness=sp(6),
        borderwidth=0,
    )

    st.configure(
        "Data.Treeview",
        background=C.CARD,
        fieldbackground=C.CARD,
        foreground=C.TEXT,
        borderwidth=0,
        rowheight=sp(34),
        font=font(10),
    )
    st.map(
        "Data.Treeview",
        background=[("selected", C.ACCENT_SOFT)],
        foreground=[("selected", "#FFFFFF")],
    )
    st.configure(
        "Data.Treeview.Heading",
        background=C.BG_DEEP,
        foreground=C.TEXT_DIM,
        relief="flat",
        borderwidth=0,
        font=font(9, "bold"),
        padding=(sp(10), sp(9)),
    )
    st.map(
        "Data.Treeview.Heading",
        background=[("active", C.CARD_ALT)],
        foreground=[("active", C.TEXT)],
    )
    st.layout("Data.Treeview", [("Data.Treeview.treearea", {"sticky": "nswe"})])

    st.configure(
        "Nav.Treeview",
        background=C.SIDEBAR,
        fieldbackground=C.SIDEBAR,
        foreground=C.TEXT_DIM,
        borderwidth=0,
        rowheight=sp(32),
        font=font(10),
    )
    st.map(
        "Nav.Treeview",
        background=[("selected", C.CARD_ALT)],
        foreground=[("selected", C.TEXT)],
    )
    st.layout("Nav.Treeview", [("Nav.Treeview.treearea", {"sticky": "nswe"})])

    st.configure(
        "TCombobox",
        fieldbackground=C.CARD_ALT,
        background=C.CARD_ALT,
        foreground=C.TEXT,
        arrowcolor=C.TEXT_DIM,
        bordercolor=C.BORDER,
        lightcolor=C.CARD_ALT,
        darkcolor=C.CARD_ALT,
        selectbackground=C.CARD_ALT,
        selectforeground=C.TEXT,
        padding=(sp(8), sp(6)),
        relief="flat",
    )
    st.map(
        "TCombobox",
        fieldbackground=[("readonly", C.CARD_ALT), ("disabled", C.CARD)],
        foreground=[("readonly", C.TEXT), ("disabled", C.TEXT_MUTED)],
        arrowcolor=[("active", C.TEXT)],
    )

    st.configure("TSeparator", background=C.BORDER_SOFT)


def entry_kwargs(bg: str | None = None, fg: str | None = None) -> dict:
    return {
        "bg": bg or C.CARD_ALT,
        "fg": fg or C.TEXT,
        "insertbackground": C.TEXT,
        "selectbackground": C.ACCENT,
        "selectforeground": "#FFFFFF",
        "relief": "flat",
        "bd": 0,
        "highlightthickness": 1,
        "highlightbackground": C.BORDER,
        "highlightcolor": C.ACCENT,
        "font": font(10),
    }
