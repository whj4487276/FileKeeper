"""系统托盘图标（纯 ctypes 调用 Win32，不依赖第三方库）。

在独立线程里创建隐藏窗口并运行消息循环，鼠标事件通过队列交给界面线程处理，
因此不会和 tkinter 的 mainloop 抢消息。
"""
from __future__ import annotations

import ctypes
import queue
import threading
from ctypes import wintypes
from pathlib import Path

from .single import TRAY_CLASS, WM_SHOW_MAIN

user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.windll.shell32
kernel32 = ctypes.windll.kernel32

# ---------------------------------------------------------------- 常量
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_COMMAND = 0x0111
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205

NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002

NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
NIF_INFO = 0x00000010

NIIF_INFO = 0x00000001
NIIF_USER = 0x00000004

IMAGE_ICON = 1
LR_LOADFROMFILE = 0x00000010
LR_DEFAULTSIZE = 0x00000040

IDI_APPLICATION = 32512

WM_APP = 0x8000
WM_TRAY = WM_APP + 1
WM_SHOW_NOTIFY = WM_APP + 2
WM_STOP = WM_APP + 3
WM_SET_HOTKEY = WM_APP + 4
WM_CLR_HOTKEY = WM_APP + 5
WM_UPDATE_TIP = WM_APP + 6
WM_HOTKEY = 0x0312


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", GUID),
        ("hBalloonIcon", wintypes.HICON),
    ]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", ctypes.c_void_p),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)

user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.DefWindowProcW.argtypes = [
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
]
user32.CreateWindowExW.restype = wintypes.HWND
user32.RegisterWindowMessageW.restype = wintypes.UINT
user32.LoadImageW.restype = wintypes.HANDLE
user32.LoadIconW.restype = wintypes.HICON
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL
user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wintypes.BOOL
user32.PrintWindow  # noqa: B018 - 触发符号存在性检查（失败也无妨）

shell32.Shell_NotifyIconW.restype = wintypes.BOOL


class TrayIcon:
    """任务栏通知区域图标。

    用法::

        tray = TrayIcon("电脑百宝箱", icon_path)
        tray.start()
        ...
        while True:
            event = tray.poll()          # "toggle" / "menu" / None
    """

    def __init__(self, tooltip: str = "电脑百宝箱", icon_file: Path | str | None = None):
        self.tooltip = tooltip
        self.icon_file = str(icon_file) if icon_file else ""
        self.events: "queue.Queue[str]" = queue.Queue()
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._hwnd = None
        self._hicon = None
        self._wndproc = None
        self._pending: list[tuple[str, str]] = []
        self._lock = threading.Lock()
        self._hotkey_lock = threading.Lock()
        self._hotkey_waiters: dict[int, tuple[threading.Event, dict]] = {}
        self._registered_hotkey_ids: set[int] = set()
        self._next_hotkey_id = 1
        self._uid = 1
        self._taskbar_created = 0
        self.failed = False

    # ------------------------------------------------------------ 对外
    def start(self, timeout: float = 3.0) -> bool:
        if self._thread is not None:
            return True
        self._thread = threading.Thread(target=self._run, name="fk-tray", daemon=True)
        self._thread.start()
        self._ready.wait(timeout)
        return not self.failed

    def poll(self) -> str | None:
        try:
            return self.events.get_nowait()
        except queue.Empty:
            return None

    def set_tooltip(self, text: str) -> None:
        self.tooltip = text[:120]
        self._post(WM_UPDATE_TIP)

    def notify(self, title: str, message: str) -> None:
        """在托盘弹出气泡提示。"""
        with self._lock:
            self._pending.append((str(title)[:60], str(message)[:200]))
        self._post(WM_SHOW_NOTIFY)

    def stop(self) -> None:
        if self._hwnd:
            user32.PostMessageW(self._hwnd, WM_STOP, 0, 0)
        self._thread = None

    # ------------------------------------------------------------ 全局热键
    def try_register_hotkey(
        self, modifiers: int, vk: int, timeout: float = 2.0
    ) -> tuple[bool, int, int]:
        """同步注册一个全局热键。

        返回 ``(是否成功, 热键 ID, Win32 错误码)``。每个热键使用独立 ID，
        这样修改绑定时可以先注册新键、成功后再注销旧键，避免空窗。
        """
        if not self._hwnd:
            return False, 0, 0
        with self._hotkey_lock:
            hotkey_id = self._next_hotkey_id_locked()
            event = threading.Event()
            holder = {"ok": False, "error": 0}
            self._hotkey_waiters[hotkey_id] = (event, holder)
        packed = ((int(modifiers) & 0xFFFF) << 16) | (int(vk) & 0xFFFF)
        if not user32.PostMessageW(self._hwnd, WM_SET_HOTKEY, hotkey_id, packed):
            error = self._last_error()
            self._discard_waiter(hotkey_id)
            return False, hotkey_id, error
        if not event.wait(timeout):
            self._discard_waiter(hotkey_id)
            return False, hotkey_id, -1
        return bool(holder["ok"]), hotkey_id, int(holder["error"])

    def try_unregister_hotkey(
        self, hotkey_id: int, timeout: float = 2.0
    ) -> tuple[bool, int]:
        """同步注销指定 ID 的热键，返回 ``(是否成功, Win32 错误码)``。"""
        if not self._hwnd:
            return False, 0
        with self._hotkey_lock:
            event = threading.Event()
            holder = {"ok": False, "error": 0}
            self._hotkey_waiters[int(hotkey_id)] = (event, holder)
        if not user32.PostMessageW(self._hwnd, WM_CLR_HOTKEY, int(hotkey_id), 0):
            error = self._last_error()
            self._discard_waiter(int(hotkey_id))
            return False, error
        if not event.wait(timeout):
            self._discard_waiter(int(hotkey_id))
            return False, -1
        return bool(holder["ok"]), int(holder["error"])

    def _next_hotkey_id_locked(self) -> int:
        for _ in range(0xBFFF):
            hotkey_id = self._next_hotkey_id
            self._next_hotkey_id = hotkey_id + 1 if hotkey_id < 0xBFFF else 1
            if (
                hotkey_id not in self._hotkey_waiters
                and hotkey_id not in self._registered_hotkey_ids
            ):
                return hotkey_id
        return 1

    def _discard_waiter(self, hotkey_id: int) -> None:
        with self._hotkey_lock:
            self._hotkey_waiters.pop(int(hotkey_id), None)

    def _resolve_hotkey(self, hotkey_id: int, ok: bool, error: int) -> None:
        with self._hotkey_lock:
            waiter = self._hotkey_waiters.pop(int(hotkey_id), None)
        if waiter is None:
            self.events.put(f"hotkey-{'ok' if ok else 'fail'}:{hotkey_id}")
            return
        event, holder = waiter
        holder["ok"] = bool(ok)
        holder["error"] = int(error or 0)
        event.set()

    def _last_error(self) -> int:
        try:
            error = int(ctypes.get_last_error() or 0)
        except Exception:
            error = 0
        if not error:
            try:
                error = int(ctypes.GetLastError() or 0)
            except Exception:
                error = 0
        return error

    def _fail_waiters(self) -> None:
        with self._hotkey_lock:
            waiters = list(self._hotkey_waiters.values())
            self._hotkey_waiters.clear()
        for event, holder in waiters:
            holder["ok"] = False
            holder["error"] = -2
            event.set()

    def _post_arg(self, message: int, wparam: int, lparam: int) -> bool:
        if self._hwnd:
            return bool(user32.PostMessageW(self._hwnd, message, wparam, lparam))
        return False

    # ------------------------------------------------------------ 内部
    def _post(self, message: int) -> None:
        if self._hwnd:
            user32.PostMessageW(self._hwnd, message, 0, 0)

    def _run(self) -> None:
        try:
            self._create_window()
        except Exception:
            self.failed = True
            self._ready.set()
            return

        self._ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def _create_window(self) -> None:
        hinstance = kernel32.GetModuleHandleW(None)
        class_name = TRAY_CLASS

        def handler(hwnd, msg, wparam, lparam):
            return self._wnd_proc(hwnd, msg, wparam, lparam)

        self._wndproc = WNDPROC(handler)
        wc = WNDCLASSW()
        wc.style = 0
        wc.lpfnWndProc = ctypes.cast(self._wndproc, ctypes.c_void_p)
        wc.cbClsExtra = 0
        wc.cbWndExtra = 0
        wc.hInstance = hinstance
        wc.hIcon = 0
        wc.hCursor = 0
        wc.hbrBackground = 0
        wc.lpszMenuName = None
        wc.lpszClassName = class_name

        if not user32.RegisterClassW(ctypes.byref(wc)):
            raise OSError("RegisterClassW 失败")

        self._taskbar_created = user32.RegisterWindowMessageW("TaskbarCreated")

        hwnd = user32.CreateWindowExW(
            0,
            class_name,
            "FileKeeperTrayWindow",
            0,
            0,
            0,
            0,
            0,
            None,
            None,
            hinstance,
            None,
        )
        if not hwnd:
            raise OSError("CreateWindowExW 失败")
        self._hwnd = hwnd
        self._add_icon()

    def _load_icon(self) -> int:
        if self.icon_file and Path(self.icon_file).exists():
            handle = user32.LoadImageW(
                None, self.icon_file, IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE
            )
            if handle:
                return int(handle)
        return int(user32.LoadIconW(None, IDI_APPLICATION))

    def _add_icon(self) -> None:
        self._hicon = self._load_icon()
        data = NOTIFYICONDATAW()
        data.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        data.hWnd = self._hwnd
        data.uID = self._uid
        data.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        data.uCallbackMessage = WM_TRAY
        data.hIcon = self._hicon
        data.szTip = self.tooltip
        if not shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(data)):
            self.failed = True

    def _remove_icon(self) -> None:
        if not self._hwnd:
            return
        data = NOTIFYICONDATAW()
        data.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        data.hWnd = self._hwnd
        data.uID = self._uid
        shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(data))

    def _show_balloon(self) -> None:
        with self._lock:
            if not self._pending:
                return
            title, message = self._pending.pop(0)
        if not self._hwnd:
            return
        data = NOTIFYICONDATAW()
        data.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        data.hWnd = self._hwnd
        data.uID = self._uid
        data.uFlags = NIF_INFO
        data.szInfoTitle = title
        data.szInfo = message
        data.dwInfoFlags = NIIF_INFO
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(data))

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_TRAY:
            code = int(lparam) & 0xFFFF
            if code in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                self.events.put("toggle")
            elif code == WM_RBUTTONUP:
                self.events.put("menu")
            return 0
        if msg == WM_SET_HOTKEY:
            hotkey_id = int(wparam)
            modifiers = (int(lparam) >> 16) & 0xFFFF
            vk = int(lparam) & 0xFFFF
            user32.UnregisterHotKey(hwnd, hotkey_id)
            ok = bool(user32.RegisterHotKey(hwnd, hotkey_id, modifiers, vk))
            error = 0 if ok else self._last_error()
            with self._hotkey_lock:
                if ok:
                    self._registered_hotkey_ids.add(hotkey_id)
                else:
                    self._registered_hotkey_ids.discard(hotkey_id)
            self._resolve_hotkey(hotkey_id, ok, error)
            return 0
        if msg == WM_CLR_HOTKEY:
            hotkey_id = int(wparam)
            ok = bool(user32.UnregisterHotKey(hwnd, hotkey_id))
            error = 0 if ok else self._last_error()
            with self._hotkey_lock:
                self._registered_hotkey_ids.discard(hotkey_id)
            self._resolve_hotkey(hotkey_id, ok, error)
            return 0
        if msg == WM_HOTKEY:
            self.events.put(f"hotkey:{int(wparam)}")
            return 0
        if msg == WM_SHOW_MAIN:
            # 第二个实例请求把主窗口叫出来
            self.events.put("show")
            return 0
        if msg == WM_UPDATE_TIP:
            data = NOTIFYICONDATAW()
            data.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
            data.hWnd = self._hwnd
            data.uID = self._uid
            data.uFlags = NIF_TIP
            data.szTip = self.tooltip
            shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(data))
            return 0
        if msg == WM_SHOW_NOTIFY:
            self._show_balloon()
            return 0
        if msg == WM_STOP:
            self._fail_waiters()
            self._remove_icon()
            user32.DestroyWindow(hwnd)
            return 0
        if msg == WM_CLOSE:
            self._fail_waiters()
            self._remove_icon()
            user32.DestroyWindow(hwnd)
            return 0
        if msg == WM_DESTROY:
            self._fail_waiters()
            user32.PostQuitMessage(0)
            return 0
        if self._taskbar_created and msg == self._taskbar_created:
            self._add_icon()
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)
