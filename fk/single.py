"""单实例控制：用命名互斥体保证同一时刻只运行一个副本。"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

ERROR_ALREADY_EXISTS = 183
MUTEX_NAME = "Local\\FileKeeperSingleInstance"

# 托盘隐藏窗口的类名（固定值，方便第二个实例找到第一个实例）
TRAY_CLASS = "FileKeeperTrayWindow"
WM_SHOW_MAIN = 0x8000 + 10  # WM_APP + 10

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.FindWindowW.restype = wintypes.HWND
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]

SW_SHOW = 5
SW_RESTORE = 9


class SingleInstance:
    """命名互斥体；进程退出（或句柄关闭）时互斥体自动释放。"""

    def __init__(self, name: str = MUTEX_NAME):
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        self._handle = kernel32.CreateMutexW(None, False, name)
        self.already_running = ctypes.get_last_error() == ERROR_ALREADY_EXISTS

    def release(self) -> None:
        if self._handle:
            try:
                kernel32.CloseHandle(self._handle)
            except Exception:
                pass
            self._handle = None

    def __del__(self) -> None:
        self.release()


def activate_existing(main_title: str = "") -> bool:
    """把已经在运行的窗口叫出来；找到并通知成功返回 True。"""
    try:
        hwnd = user32.FindWindowW(TRAY_CLASS, None)
        if hwnd:
            user32.PostMessageW(hwnd, WM_SHOW_MAIN, 0, 0)
            return True
    except Exception:
        pass

    if main_title:
        try:
            hwnd = user32.FindWindowW(None, main_title)
            if hwnd:
                user32.ShowWindow(hwnd, SW_RESTORE)
                user32.ShowWindow(hwnd, SW_SHOW)
                user32.SetForegroundWindow(hwnd)
                return True
        except Exception:
            pass
    return False
