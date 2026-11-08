"""全局快捷键的解析、格式化、按键映射与显示。

只处理「修饰键 + 主键」本身，不涉及注册/冲突检测（见 ``fk.hotkeys``）。
"""
from __future__ import annotations

import ctypes

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

ALL_MODIFIERS = MOD_CONTROL | MOD_ALT | MOD_SHIFT | MOD_WIN

# 首选键：和 QQ / 微信 / 截图工具的习惯保持一致
DEFAULT_HOTKEY = "Ctrl+Alt+A"

# 旧版本用过的默认键 / 自动降级键。升级时这些值会被改回 DEFAULT_HOTKEY。
LEGACY_DEFAULT_HOTKEYS = {"Alt+Shift+S", "Ctrl+Shift+F9", "Ctrl+Alt+F11"}

# 旧版本的备用键列表，仅用于配置迁移兼容
FALLBACK_HOTKEYS = ["Ctrl+Shift+F9", "Ctrl+Alt+F11", "Alt+Shift+S"]

VK_BACK = 0x08
VK_TAB = 0x09
VK_RETURN = 0x0D
VK_ESCAPE = 0x1B
VK_SPACE = 0x20
VK_PRIOR = 0x21
VK_NEXT = 0x22
VK_END = 0x23
VK_HOME = 0x24
VK_LEFT = 0x25
VK_UP = 0x26
VK_RIGHT = 0x27
VK_DOWN = 0x28
VK_INSERT = 0x2D
VK_DELETE = 0x2E
VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_F1 = 0x70
VK_F4 = 0x73
VK_F9 = 0x78
VK_F12 = 0x7B
VK_F24 = 0x87

_MODIFIER_NAMES = {
    "CTRL": MOD_CONTROL,
    "CONTROL": MOD_CONTROL,
    "ALT": MOD_ALT,
    "SHIFT": MOD_SHIFT,
    "WIN": MOD_WIN,
    "WINDOWS": MOD_WIN,
    "SUPER": MOD_WIN,
}

_NAMED_KEYS = {
    "SPACE": VK_SPACE,
    "TAB": VK_TAB,
    "ENTER": VK_RETURN,
    "RETURN": VK_RETURN,
    "ESC": VK_ESCAPE,
    "ESCAPE": VK_ESCAPE,
    "BACKSPACE": VK_BACK,
    "INSERT": VK_INSERT,
    "DELETE": VK_DELETE,
    "HOME": VK_HOME,
    "END": VK_END,
    "PAGEUP": VK_PRIOR,
    "PAGEDOWN": VK_NEXT,
    "PRIOR": VK_PRIOR,
    "NEXT": VK_NEXT,
    "LEFT": VK_LEFT,
    "RIGHT": VK_RIGHT,
    "UP": VK_UP,
    "DOWN": VK_DOWN,
}
for _index in range(1, 25):
    _NAMED_KEYS[f"F{_index}"] = 0x6F + _index

_VK_NAMES = {
    VK_SPACE: "Space",
    VK_TAB: "Tab",
    VK_RETURN: "Enter",
    VK_ESCAPE: "Esc",
    VK_BACK: "Backspace",
    VK_INSERT: "Insert",
    VK_DELETE: "Delete",
    VK_HOME: "Home",
    VK_END: "End",
    VK_PRIOR: "PageUp",
    VK_NEXT: "PageDown",
    VK_LEFT: "Left",
    VK_RIGHT: "Right",
    VK_UP: "Up",
    VK_DOWN: "Down",
}
for _index in range(1, 25):
    _VK_NAMES[0x6F + _index] = f"F{_index}"

_MODIFIER_KEYSYMS = {
    "Control_L",
    "Control_R",
    "Alt_L",
    "Alt_R",
    "Shift_L",
    "Shift_R",
    "Super_L",
    "Super_R",
    "Win_L",
    "Win_R",
    "Meta_L",
    "Meta_R",
    "Caps_Lock",
    "Num_Lock",
}

try:
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
except Exception:  # pragma: no cover - 非 Windows
    _user32 = None


def key_name(vk: int) -> str:
    """把虚拟键码转成当前键盘布局下可读的名字。"""
    vk = int(vk or 0)
    if vk in _VK_NAMES:
        return _VK_NAMES[vk]
    if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
        char = ""
        if _user32 is not None:
            try:
                mapped = int(_user32.MapVirtualKeyW(vk, 2)) & 0xFFFF
                if mapped:
                    char = chr(mapped)
            except Exception:
                char = ""
        if not char:
            char = chr(vk)
        return char.upper() if char.isalpha() else char
    return f"VK{vk}"


def format_hotkey(modifiers: int, vk: int, spaced: bool = False) -> str:
    """把 (修饰键掩码, 主键 VK) 格式化成字符串。"""
    parts: list[str] = []
    if modifiers & MOD_CONTROL:
        parts.append("Ctrl")
    if modifiers & MOD_ALT:
        parts.append("Alt")
    if modifiers & MOD_SHIFT:
        parts.append("Shift")
    if modifiers & MOD_WIN:
        parts.append("Win")
    if vk:
        parts.append(key_name(vk))
    separator = " + " if spaced else "+"
    return separator.join(parts)


def parse_binding(text: str) -> tuple[int, int] | None:
    """把 ``"Ctrl+Alt+A"`` 解析成 ``(修饰键掩码, VK)``；不合法返回 None。"""
    parts = [chunk.strip().upper() for chunk in str(text or "").split("+") if chunk.strip()]
    if not parts:
        return None
    modifiers = 0
    vk = None
    for part in parts:
        if part in _MODIFIER_NAMES:
            modifiers |= _MODIFIER_NAMES[part]
        elif len(part) == 1 and part.isalnum():
            vk = ord(part)
        elif part in _NAMED_KEYS:
            vk = _NAMED_KEYS[part]
        else:
            return None
    if vk is None or modifiers == 0:
        return None
    return modifiers & ALL_MODIFIERS, vk


def parse_hotkey(text: str) -> tuple[int, int] | None:
    """兼容旧接口：返回带 ``MOD_NOREPEAT`` 的 ``(modifiers, vk)``。"""
    parsed = parse_binding(text)
    if parsed is None:
        return None
    return parsed[0] | MOD_NOREPEAT, parsed[1]


def modifier_bit(keysym: str) -> int:
    """单个修饰键 keysym 对应的掩码；不是修饰键返回 0。"""
    keysym = str(keysym or "")
    if keysym in ("Control_L", "Control_R"):
        return MOD_CONTROL
    if keysym in ("Alt_L", "Alt_R"):
        return MOD_ALT
    if keysym in ("Shift_L", "Shift_R"):
        return MOD_SHIFT
    if keysym in ("Super_L", "Super_R", "Win_L", "Win_R", "Meta_L", "Meta_R"):
        return MOD_WIN
    return 0


def modifiers_from_state(state: int) -> int:
    """从 Tk 的 event.state 提取修饰键。"""
    state = int(state or 0)
    modifiers = 0
    if state & 0x0004:
        modifiers |= MOD_CONTROL
    if state & 0x0001:
        modifiers |= MOD_SHIFT
    if state & 0x20000 or state & 0x0008:
        modifiers |= MOD_ALT
    if state & 0x0040 or state & 0x40000:
        modifiers |= MOD_WIN
    return modifiers


def keysym_to_vk(keysym: str) -> int | None:
    """把 Tk keysym 转成 Windows VK。"""
    keysym = str(keysym or "")
    if not keysym:
        return None
    if len(keysym) == 1 and keysym.isalnum():
        return ord(keysym.upper())
    upper = keysym.upper()
    if upper in _NAMED_KEYS:
        return _NAMED_KEYS[upper]
    return None


def from_tk_event(keysym: str, state: int) -> tuple[int, int] | None:
    """兼容旧接口：把 tkinter 按键事件转成 ``(modifiers|NOREPEAT, vk)``。"""
    if not keysym or keysym in _MODIFIER_KEYSYMS:
        return None
    vk = keysym_to_vk(keysym)
    modifiers = modifiers_from_state(state) & ALL_MODIFIERS
    if vk is None or modifiers == 0:
        return None
    return modifiers | MOD_NOREPEAT, vk
