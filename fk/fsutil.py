"""文件系统与 Windows shell 工具函数。"""
from __future__ import annotations

import ctypes
import os
import shutil
import string
import subprocess
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------- 时间 / 格式化

ISO_FMT = "%Y-%m-%dT%H:%M:%S"


def now_iso() -> str:
    return datetime.now().strftime(ISO_FMT)


def parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    for fmt in (ISO_FMT, "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except (ValueError, TypeError):
            continue
    return None


def human_size(num: int | float | None) -> str:
    if num is None:
        return "—"
    try:
        value = float(num)
    except (TypeError, ValueError):
        return "—"
    if value < 1024:
        return f"{int(value)} B"
    for unit in ("KB", "MB", "GB", "TB"):
        value /= 1024.0
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"
    return f"{value:.1f} TB"


def human_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    total = int(round(seconds))
    if total < 60:
        return f"{total} 秒"
    minutes, sec = divmod(total, 60)
    if minutes < 60:
        return f"{minutes} 分 {sec} 秒"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} 小时 {minutes} 分"


def human_ago(value: str | None) -> str:
    dt = parse_iso(value or "")
    if not dt:
        return "从未"
    delta = (datetime.now() - dt).total_seconds()
    if delta < 0:
        return "刚刚"
    if delta < 60:
        return "刚刚"
    if delta < 3600:
        return f"{int(delta // 60)} 分钟前"
    if delta < 86400:
        return f"{int(delta // 3600)} 小时前"
    if delta < 86400 * 7:
        return f"{int(delta // 86400)} 天前"
    return dt.strftime("%Y-%m-%d")


def human_time(value: str | None) -> str:
    dt = parse_iso(value or "")
    if not dt:
        return "—"
    return dt.strftime("%Y-%m-%d %H:%M")


def weekday_name(index: int) -> str:
    names = ["一", "二", "三", "四", "五", "六", "日"]
    if 1 <= index <= 7:
        return names[index - 1]
    return "?"


# ---------------------------------------------------------------- 路径工具


def long_path(value) -> str:
    """超过 MAX_PATH 时加上 \\\\?\\ 前缀，避免长路径失败。"""
    text = str(value)
    if text.startswith("\\\\?\\"):
        return text
    if len(text) < 248:
        return text
    if text.startswith("\\\\"):
        return "\\\\?\\UNC\\" + text[2:]
    return "\\\\?\\" + text


def is_inside(child, parent) -> bool:
    """parent 是否包含 child（含相等）。"""
    try:
        c = Path(child).resolve()
        p = Path(parent).resolve()
    except (OSError, ValueError):
        return False
    if c == p:
        return True
    try:
        c.relative_to(p)
        return True
    except ValueError:
        return False


def sanitize_name(name: str) -> str:
    bad = '<>:"/\\|?*'
    out = "".join("_" if ch in bad else ch for ch in str(name)).strip().strip(".")
    return out or "未命名"


def ensure_dir(path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def list_drives() -> list[tuple[str, str, int, int]]:
    """返回 [(根路径, 卷标, 总量, 可用量)]。"""
    result: list[tuple[str, str, int, int]] = []
    for letter in string.ascii_uppercase:
        root = f"{letter}:\\"
        if not os.path.exists(root):
            continue
        total, free = disk_usage(root)
        label = ""
        try:
            vol = ctypes.create_unicode_buffer(261)
            ctypes.windll.kernel32.GetVolumeInformationW(
                ctypes.c_wchar_p(root), vol, 261, None, None, None, None, 0
            )
            label = vol.value
        except Exception:
            label = ""
        result.append((root, label, total, free))
    return result


def disk_usage(path) -> tuple[int, int]:
    """返回 (总容量, 可用容量)，失败返回 (0, 0)。"""
    free = ctypes.c_ulonglong(0)
    total = ctypes.c_ulonglong(0)
    total_free = ctypes.c_ulonglong(0)
    try:
        ok = ctypes.windll.kernel32.GetDiskFreeSpaceExW(
            ctypes.c_wchar_p(str(path)),
            ctypes.byref(free),
            ctypes.byref(total),
            ctypes.byref(total_free),
        )
        if not ok:
            return 0, 0
        return int(total.value), int(free.value)
    except Exception:
        return 0, 0


def folder_size(path, limit: int = 400000) -> tuple[int, int]:
    """统计目录大小，返回 (总字节, 文件数)。超大目录会提前停止。"""
    total = 0
    count = 0
    try:
        for root, _dirs, files in os.walk(long_path(path), onerror=lambda e: None):
            for name in files:
                try:
                    total += os.stat(os.path.join(root, name), follow_symlinks=False).st_size
                except OSError:
                    continue
                count += 1
                if count >= limit:
                    return total, count
    except OSError:
        pass
    return total, count


# ---------------------------------------------------------------- Shell 集成


class _SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", ctypes.c_ushort),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]


_FO_DELETE = 3
_FOF_SILENT = 0x0004
_FOF_NOCONFIRMATION = 0x0010
_FOF_ALLOWUNDO = 0x0040
_FOF_NOERRORUI = 0x0400


def move_to_recycle_bin(paths) -> None:
    """把文件/目录移入 Windows 回收站（可撤销）。"""
    items = [str(p) for p in paths]
    if not items:
        return
    joined = "\0".join(items) + "\0\0"
    buf = ctypes.create_unicode_buffer(joined)
    op = _SHFILEOPSTRUCTW()
    op.hwnd = None
    op.wFunc = _FO_DELETE
    op.pFrom = ctypes.cast(buf, wintypes.LPCWSTR)
    op.pTo = None
    op.fFlags = (
        _FOF_ALLOWUNDO | _FOF_NOCONFIRMATION | _FOF_NOERRORUI | _FOF_SILENT
    )
    code = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if code != 0:
        raise OSError(f"无法移入回收站（错误码 {code}）")


def open_folder(path) -> None:
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(str(target))
    os.startfile(str(target))  # noqa: S606 - Windows shell 打开


def reveal_in_explorer(path) -> None:
    target = Path(path)
    if target.is_dir():
        open_folder(target)
        return
    if target.exists():
        subprocess.Popen(["explorer", "/select,", str(target)])
    else:
        parent = target.parent
        if parent.exists():
            open_folder(parent)
        else:
            raise FileNotFoundError(str(target))


def copy_tree(src, dst) -> int:
    """递归复制目录，返回复制的文件数。"""
    count = 0
    src_str = str(src)
    dst_p = Path(dst)
    for root, _dirs, files in os.walk(src_str, onerror=lambda e: None):
        relative = os.path.relpath(root, src_str)
        out_dir = dst_p if relative == "." else dst_p / relative
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        for name in files:
            try:
                shutil.copy2(os.path.join(root, name), out_dir / name)
                count += 1
            except OSError:
                continue
    return count


# ---------------------------------------------------------------- 文件分类

CATEGORIES: list[tuple[str, str, tuple[str, ...]]] = [
    (
        "图片",
        "image",
        (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".ico", ".heic", ".tif", ".tiff"),
    ),
    (
        "视频",
        "video",
        (".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".rmvb", ".ts", ".m4v", ".webm"),
    ),
    (
        "音频",
        "audio",
        (".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma", ".ape"),
    ),
    (
        "文档",
        "doc",
        (".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".pdf", ".txt", ".md", ".rtf", ".csv", ".epub"),
    ),
    (
        "压缩包",
        "archive",
        (".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".iso"),
    ),
    (
        "程序",
        "app",
        (".exe", ".msi", ".dll", ".bat", ".cmd", ".ps1", ".jar", ".apk"),
    ),
    (
        "代码",
        "code",
        (".py", ".js", ".ts", ".html", ".css", ".json", ".xml", ".c", ".cpp", ".h", ".cs", ".java", ".go", ".rs", ".sql", ".yml", ".yaml"),
    ),
]

_CATEGORY_BY_EXT: dict[str, str] = {}
for _name, _key, _exts in CATEGORIES:
    for _ext in _exts:
        _CATEGORY_BY_EXT[_ext] = _name


def file_category(path) -> str:
    ext = Path(path).suffix.lower()
    return _CATEGORY_BY_EXT.get(ext, "其他")


def file_type_label(path) -> str:
    ext = Path(path).suffix.lower()
    if not ext:
        return "文件"
    return f"{ext.lstrip('.').upper()} 文件"
