"""开机自动启动（写入 HKCU 的 Run 注册表项）。

只影响当前用户，不需要管理员权限；卸载时把开关关掉即可清除。
"""
from __future__ import annotations

import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "FileKeeper"
ARG_MINIMIZED = "--minimized"


def _winreg():
    import winreg  # 延迟导入，方便在非 Windows 上做静态检查

    return winreg


def python_executable() -> Path:
    """优先返回 pythonw.exe（启动时不弹黑窗口）。"""
    exe = Path(sys.executable)
    if exe.name.lower() == "python.exe":
        candidate = exe.with_name("pythonw.exe")
        if candidate.exists():
            return candidate
    return exe


def launch_command() -> str:
    """生成写入注册表的启动命令。"""
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable).resolve()}" {ARG_MINIMIZED}'
    main_py = Path(__file__).resolve().parent.parent / "main.py"
    return f'"{python_executable()}" "{main_py}" {ARG_MINIMIZED}'


def current_command(value_name: str = VALUE_NAME) -> str | None:
    try:
        winreg = _winreg()
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _kind = winreg.QueryValueEx(key, value_name)
            return str(value)
    except OSError:
        return None
    except Exception:
        return None


def is_enabled(value_name: str = VALUE_NAME) -> bool:
    return current_command(value_name) is not None


def enable(value_name: str = VALUE_NAME) -> bool:
    """写入/更新自启项，返回是否成功。"""
    try:
        winreg = _winreg()
        command = launch_command()
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(key, value_name, 0, winreg.REG_SZ, command)
        return True
    except Exception:
        return False


def disable(value_name: str = VALUE_NAME) -> bool:
    try:
        winreg = _winreg()
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, value_name)
        return True
    except FileNotFoundError:
        return True
    except OSError:
        return False
    except Exception:
        return False


def sync(enabled: bool, value_name: str = VALUE_NAME) -> bool:
    """让注册表状态与设置保持一致。

    - 开启：不存在或路径已变（挪动了程序目录）时重新写入；
    - 关闭：存在则删除。
    """
    if enabled:
        expected = launch_command()
        if current_command(value_name) == expected:
            return True
        return enable(value_name)
    return disable(value_name)
