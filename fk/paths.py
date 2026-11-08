"""应用路径与常量。

设计原则：**便携优先**。配置与日志默认写在程序所在目录的 ``data\\`` 下，
这样把整个文件夹拷到 U 盘 / 另一台电脑（甚至重装系统后）就能直接继续用。
只有当程序目录不可写（例如放在 Program Files 又没有管理员权限）时，
才回退到 %APPDATA%。
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_NAME = "FileKeeper"  # 内部标识：注册表项 / 旧版配置目录
APP_TITLE = "电脑百宝箱"  # 界面上显示的名称
APP_VERSION = "2.2.1"
APP_TAGLINE = "备份 · 定时关机 · 时间闹钟 · 计时器 · 截图"

DATA_DIR_NAME = "data"

_resolved_data_dir: Path | None = None


def app_dir() -> Path:
    """程序所在目录（打包后为 exe 目录）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_dir() -> Path:
    """只读资源目录（PyInstaller 解包目录）。"""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base)
    return app_dir()


def legacy_data_dir() -> Path:
    """1.0 版本使用过的 %APPDATA% 目录。"""
    root = os.environ.get("APPDATA") or str(Path.home())
    return Path(root) / APP_NAME


def _writable(target: Path) -> bool:
    try:
        target.mkdir(parents=True, exist_ok=True)
        probe = target / ".fk_write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def data_dir() -> Path:
    """可写的用户数据目录（便携优先）。"""
    global _resolved_data_dir
    if _resolved_data_dir is not None:
        return _resolved_data_dir

    portable = app_dir() / DATA_DIR_NAME
    if _writable(portable):
        _resolved_data_dir = portable
        _migrate_legacy(portable)
        return portable

    fallback = legacy_data_dir()
    fallback.mkdir(parents=True, exist_ok=True)
    _resolved_data_dir = fallback
    return fallback


def _migrate_legacy(target: Path) -> None:
    """把旧版 %APPDATA% 里的配置搬到便携目录（只做一次）。"""
    try:
        old = legacy_data_dir()
        if old.resolve() == target.resolve():
            return
        old_config = old / "config.json"
        new_config = target / "config.json"
        if old_config.exists() and not new_config.exists():
            shutil.copy2(old_config, new_config)
        old_log = old / "app.log"
        new_log = target / "app.log"
        if old_log.exists() and not new_log.exists():
            shutil.copy2(old_log, new_log)
    except OSError:
        pass


def is_portable() -> bool:
    try:
        return data_dir().parent == app_dir()
    except OSError:
        return False


def config_file() -> Path:
    return data_dir() / "config.json"


def log_file() -> Path:
    return data_dir() / "app.log"


def pictures_dir() -> Path:
    """系统“图片”文件夹。

    使用 ``SHGetKnownFolderPath(FOLDERID_Pictures)``，这样中文系统、
    OneDrive 重定向或用户手动改过位置时都能拿到正确路径，而不是硬编码
    ``C:\\Users\\xxx\\Pictures``。
    """
    try:
        import ctypes
        from ctypes import wintypes

        class _GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", wintypes.DWORD),
                ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8),
            ]

        guid = _GUID()
        guid.Data1 = 0x33E28130
        guid.Data2 = 0x4E1E
        guid.Data3 = 0x4676
        for index, value in enumerate((0x83, 0x5A, 0x98, 0x39, 0x5C, 0x3B, 0xC3, 0xBB)):
            guid.Data4[index] = value

        shell32 = ctypes.windll.shell32
        ole32 = ctypes.windll.ole32
        shell32.SHGetKnownFolderPath.argtypes = [
            ctypes.POINTER(_GUID),
            wintypes.DWORD,
            wintypes.HANDLE,
            ctypes.POINTER(ctypes.c_wchar_p),
        ]
        shell32.SHGetKnownFolderPath.restype = ctypes.c_long
        ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]

        pointer = ctypes.c_wchar_p()
        result = shell32.SHGetKnownFolderPath(
            ctypes.byref(guid), 0, None, ctypes.byref(pointer)
        )
        if result == 0 and pointer.value:
            path = Path(pointer.value)
            ole32.CoTaskMemFree(ctypes.cast(pointer, ctypes.c_void_p))
            if path.exists():
                return path
    except Exception:
        pass

    fallback = Path.home() / "Pictures"
    if fallback.exists():
        return fallback
    return Path.home()


def icon_path(name: str) -> Path:
    return resource_dir() / "assets" / "icons" / name


def app_icon() -> Path:
    return resource_dir() / "assets" / "app.ico"


def last_fixed_drive() -> str | None:
    """返回本机最后一个固定磁盘的根路径（如 ``E:\\``）。"""
    import ctypes
    import string

    kernel32 = ctypes.windll.kernel32
    drives: list[str] = []
    try:
        mask = int(kernel32.GetLogicalDrives())
    except Exception:
        mask = 0
    for index, letter in enumerate(string.ascii_uppercase):
        if not (mask & (1 << index)):
            continue
        root = f"{letter}:\\"
        try:
            kind = kernel32.GetDriveTypeW(ctypes.c_wchar_p(root))
        except Exception:
            kind = 3
        if kind == 3:  # DRIVE_FIXED
            drives.append(root)
    return drives[-1] if drives else None


def backup_folder_name() -> str:
    return f"{APP_TITLE}备份"


def default_backup_root() -> str:
    """默认主备份文件夹：最后一个盘符下的「电脑百宝箱备份」。"""
    drive = last_fixed_drive()
    if drive:
        return str(Path(drive) / backup_folder_name())
    return str(Path.home() / backup_folder_name())

