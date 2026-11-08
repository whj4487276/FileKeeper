"""截图保存：文件名清洗、路径校验、原子写入与并发控制。"""
from __future__ import annotations

import errno
import ntpath
import os
import re
import stat
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import capture as cap_mod

SUPPORTED_FORMAT = "png"
SUPPORTED_EXTENSION = ".png"
NETWORK_SAVE_TIMEOUT = 10.0

ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".gif",
    ".webp",
    ".tif",
    ".tiff",
}
RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

try:
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.windll.kernel32
    _kernel32.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
    _kernel32.GetDriveTypeW.restype = wintypes.UINT
except Exception:  # pragma: no cover - 非 Windows
    _kernel32 = None


@dataclass
class FilenameResult:
    filename: str = ""
    notes: list[str] = field(default_factory=list)
    error: str = ""


@dataclass
class SaveResult:
    ok: bool
    message: str = ""
    error_code: int = 0


class SaveError(Exception):
    def __init__(self, message: str, error_code: int = 0):
        super().__init__(message)
        self.message = message
        self.error_code = error_code


def default_screenshot_name(now: datetime | None = None) -> str:
    """百宝箱 + 当天日期 + 当前时间（精确到分）。"""
    now = now or datetime.now()
    return f"百宝箱{now:%Y%m%d}_{now:%H%M}"


def suggest_default_name(now: datetime | None = None) -> str:
    return default_screenshot_name(now) + SUPPORTED_EXTENSION


def normalize_filename(name: str, fmt: str = SUPPORTED_FORMAT) -> FilenameResult:
    """清洗用户输入的文件名。

    - 非法字符替换成 ``_``；
    - 去掉 Windows 会吞掉的末尾空格/点；
    - 保留名（CON、PRN、COM1…）直接拒绝；
    - 只支持 PNG；其他扩展名改为 ``.png``，没有扩展名则自动补上。
    """
    result = FilenameResult()
    raw = str(name or "")
    if not raw.strip():
        result.error = "请输入文件名"
        return result

    trimmed = raw.rstrip(" .")
    if trimmed != raw:
        result.notes.append("文件名末尾的空格/点已去除（Windows 会自动删除）")
    raw = trimmed
    stem, extension = ntpath.splitext(raw)
    if extension.lower() not in ("", ".", SUPPORTED_EXTENSION):
        result.notes.append(
            f"当前仅支持 PNG，扩展名已由 {extension} 改为 {SUPPORTED_EXTENSION}"
        )
    elif extension == ".":
        result.notes.append("文件名末尾的点已去除，并自动补上 .png")

    # 有些保存对话框会在用户输入 foo.jpg 后自动补成 foo.jpg.png
    inner_stem, inner_ext = ntpath.splitext(stem)
    if inner_ext.lower() in IMAGE_EXTENSIONS:
        stem = inner_stem
        if inner_ext.lower() != SUPPORTED_EXTENSION:
            result.notes.append(
                f"文件名中的 {inner_ext} 与当前 PNG 格式不一致，已统一改为 .png"
            )
        else:
            result.notes.append("重复的 .png 扩展名已合并")

    cleaned_stem = stem.rstrip(" .")
    if cleaned_stem != stem:
        result.notes.append("文件名末尾的空格/点已去除（Windows 会自动删除）")

    cleaned_stem = ILLEGAL_CHARS.sub("_", cleaned_stem)
    if cleaned_stem != stem:
        result.notes.append('文件名中的 \\ / : * ? " < > | 等字符已替换为下划线')

    cleaned_stem = cleaned_stem.rstrip(" .")
    if not cleaned_stem:
        result.error = "文件名不能为空"
        return result

    base = cleaned_stem.split(".")[0].strip().upper()
    if base in RESERVED_NAMES:
        result.error = (
            f"「{base}」是 Windows 保留名，不能用作文件名（加扩展名也不行）"
        )
        return result

    filename = cleaned_stem + SUPPORTED_EXTENSION
    if len(filename) > 255:
        result.error = "文件名过长，请少于 200 个字符"
        return result
    result.filename = filename
    return result


def normalize_save_path(path: str, fmt: str = SUPPORTED_FORMAT) -> tuple[Path | None, list[str], str]:
    """对完整路径中的文件名部分做清洗，返回 ``(路径, 提示, 错误)``。"""
    target = Path(path)
    if not target.name:
        return None, [], "请输入文件名"
    result = normalize_filename(target.name, fmt)
    if result.error:
        return None, result.notes, result.error
    return target.with_name(result.filename), result.notes, ""


def is_network_path(path) -> bool:
    raw = str(path)
    if raw.startswith("\\\\") or raw.startswith("//"):
        return True
    drive, _rest = ntpath.splitdrive(raw)
    if not drive:
        return False
    if _kernel32 is not None:
        try:
            if int(_kernel32.GetDriveTypeW(drive + "\\")) == 4:  # DRIVE_REMOTE
                return True
        except Exception:
            pass
    return False


def check_directory(path) -> str | None:
    """检查盘符/目录是否存在且可写；返回错误文案或 None。"""
    target = Path(path)
    directory = target.parent

    drive, _rest = ntpath.splitdrive(str(target))
    if drive:
        root = drive + "\\" if not drive.startswith("\\\\") else drive
        try:
            if not os.path.exists(root):
                return f"盘符或共享路径不存在：{drive}"
        except OSError:
            return f"无法访问盘符或共享路径：{drive}"

    if not directory.exists():
        return f"保存目录不存在：\n{directory}"
    if not directory.is_dir():
        return f"保存位置不是文件夹：\n{directory}"

    try:
        with tempfile.NamedTemporaryFile(
            dir=directory, prefix=".fk_write_test_", suffix=".tmp", delete=True
        ):
            pass
    except OSError as exc:
        return _directory_error(exc, directory)
    return None


def check_target_file(path) -> str | None:
    target = Path(path)
    if not target.exists():
        return None
    if target.is_dir():
        return f"目标位置已经有一个同名文件夹：\n{target}"
    try:
        mode = target.stat().st_mode
        if not mode & stat.S_IWRITE:
            return f"目标文件是只读文件，无法覆盖：\n{target}\n\n请取消只读属性或换一个文件名。"
        if not os.access(target, os.W_OK):
            return f"没有权限覆盖这个文件：\n{target}"
    except OSError as exc:
        return _file_error(exc, target)
    return None


def save_png_atomic(path, image, cancel_check=None) -> None:
    """先写同目录临时文件，再原子替换目标，避免留下半成品。"""
    if cancel_check is not None and cancel_check():
        raise SaveError("保存已取消")
    target = Path(path)
    directory = target.parent
    try:
        fd, temp_name = tempfile.mkstemp(
            dir=directory, prefix=".fk_shot_", suffix=".tmp"
        )
        os.close(fd)
    except OSError as exc:
        raise SaveError(_write_error(exc, target), getattr(exc, "errno", 0) or 0)
    temp_path = Path(temp_name)
    try:
        cap_mod.save_png(temp_path, image)
        if cancel_check is not None and cancel_check():
            raise SaveError("保存已取消")
        os.replace(temp_path, target)
    except SaveError:
        raise
    except OSError as exc:
        raise SaveError(_write_error(exc, target), getattr(exc, "errno", 0) or 0)
    except Exception as exc:  # noqa: BLE001
        raise SaveError(f"写入截图失败：{exc}", 0)
    finally:
        try:
            if temp_path.exists():
                temp_path.unlink()
        except OSError:
            pass


def _directory_error(exc: OSError, directory: Path) -> str:
    code = getattr(exc, "errno", 0)
    winerror = getattr(exc, "winerror", 0) or 0
    if code == errno.ENOSPC or winerror in (39, 112):
        return f"磁盘空间不足，无法在以下目录保存：\n{directory}"
    if code in (errno.EACCES, errno.EPERM) or winerror in (5, 32):
        return (
            f"没有写入权限：\n{directory}\n\n"
            "请换一个有权限的文件夹，或以管理员身份运行。"
        )
    return f"无法写入保存目录：\n{directory}\n\n{exc}"


def _file_error(exc: OSError, target: Path) -> str:
    code = getattr(exc, "errno", 0)
    winerror = getattr(exc, "winerror", 0) or 0
    if code in (errno.EACCES, errno.EPERM) or winerror in (5, 32):
        return f"没有权限访问目标文件：\n{target}"
    return f"无法访问目标文件：\n{target}\n\n{exc}"


def _write_error(exc: OSError, target: Path) -> str:
    code = getattr(exc, "errno", 0)
    winerror = getattr(exc, "winerror", 0) or 0
    if code == errno.ENOSPC or winerror in (39, 112):
        return "磁盘空间不足，保存失败。\n\n请清理磁盘后重试。"
    if code in (errno.EACCES, errno.EPERM) or winerror in (5, 32):
        return (
            f"没有写入权限，或目标文件是只读文件：\n{target}\n\n"
            "请换一个位置，或取消文件的只读属性。"
        )
    if code == errno.ENOENT:
        return f"保存目录不存在：\n{target.parent}"
    if code == errno.ENAMETOOLONG:
        return "文件名或路径过长，请换一个短一点的名字。"
    return f"写入失败：\n{target}\n\n{exc}"


class SaveGate:
    """保证同一时间只有一个截图保存流程。"""

    def __init__(self):
        self._lock = threading.Lock()

    def acquire(self) -> bool:
        return self._lock.acquire(blocking=False)

    def release(self) -> None:
        try:
            self._lock.release()
        except RuntimeError:
            pass

    @property
    def locked(self) -> bool:
        return self._lock.locked()


SAVE_GATE = SaveGate()


def save_in_progress() -> bool:
    return SAVE_GATE.locked
