"""备份日志：每次备份往任务目录下的「备份日志.txt」追加一行。

行格式：``备份时间 | 结果 | 备份的文件``
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

LOG_NAME = "备份日志.txt"

HEADER = (
    "# 电脑百宝箱 · 备份日志\r\n"
    "# 格式：备份时间 | 结果 | 备份的文件\r\n"
    "# ------------------------------------------------------------\r\n"
)

STATUS_TEXT = {
    "success": "成功",
    "partial": "部分成功",
    "failed": "失败",
    "cancelled": "已取消",
}

MAX_NAMES = 10


def log_path(target) -> Path | None:
    text = str(target or "").strip()
    if not text:
        return None
    return Path(text) / LOG_NAME


def format_line(result, when: datetime | None = None) -> str:
    stamp = (when or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    status = STATUS_TEXT.get(getattr(result, "status", ""), getattr(result, "status", "") or "未知")

    names = list(getattr(result, "files", []) or [])
    if names:
        shown = "、".join(names[:MAX_NAMES])
        if len(names) > MAX_NAMES:
            shown += f" 等 {len(names)} 个文件"
    elif getattr(result, "skipped", 0):
        shown = "（没有文件变化）"
    else:
        shown = "（没有文件）"

    return f"{stamp} | {status} | {shown}\r\n"


def append_result(task, result, when: datetime | None = None) -> Path | None:
    """把一次备份结果写进任务的日志文件；失败时静默返回 None。"""
    path = log_path(getattr(task, "target", ""))
    if path is None:
        return None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        is_new = not path.exists() or path.stat().st_size == 0
        with open(path, "a", encoding="utf-8", newline="") as handle:
            if is_new:
                handle.write("\ufeff")  # 让记事本正确识别 UTF-8
                handle.write(HEADER)
            handle.write(format_line(result, when))
        return path
    except OSError:
        return None


def read_tail(task, limit: int = 200) -> list[str]:
    """读取日志的最后若干行（调试/展示用）。"""
    path = log_path(getattr(task, "target", ""))
    if path is None or not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as handle:
            lines = handle.read().splitlines()
        return lines[-limit:]
    except OSError:
        return []
