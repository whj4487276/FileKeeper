"""备份引擎：多来源扫描、复制、智能挑选、快照清理、还原。"""
from __future__ import annotations

import fnmatch
import os
import re
import shutil
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator

from .fsutil import human_size, long_path

SNAPSHOT_RE = re.compile(r"^\d{8}-\d{6}(-\d+)?$")


def _path_exists(path) -> bool:
    try:
        return os.path.exists(long_path(str(path)))
    except OSError:
        return False


def _path_is_dir(path) -> bool:
    try:
        return os.path.isdir(long_path(str(path)))
    except OSError:
        return False


def _path_is_file(path) -> bool:
    try:
        return os.path.isfile(long_path(str(path)))
    except OSError:
        return False


class BackupCancelled(Exception):
    """用户主动取消。"""


@dataclass
class Progress:
    phase: str = "scan"
    total_files: int = 0
    done_files: int = 0
    total_bytes: int = 0
    done_bytes: int = 0
    current: str = ""
    detail: str = ""

    @property
    def percent(self) -> float:
        if self.total_files <= 0:
            return 0.0
        return min(100.0, self.done_files * 100.0 / self.total_files)

    def copy(self) -> "Progress":
        return Progress(
            phase=self.phase,
            total_files=self.total_files,
            done_files=self.done_files,
            total_bytes=self.total_bytes,
            done_bytes=self.done_bytes,
            current=self.current,
            detail=self.detail,
        )


@dataclass
class RestorePlan:
    files: int = 0
    conflicts: int = 0
    total_bytes: int = 0
    errors: list[str] = field(default_factory=list)
    cancelled: bool = False


@dataclass
class Result:
    ok: bool = False
    status: str = "failed"
    copied: int = 0
    skipped: int = 0
    deleted: int = 0
    bytes_copied: int = 0
    total_files: int = 0
    duration: float = 0.0
    dest: str = ""
    snapshot: str = ""
    note: str = ""
    files: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        if self.status == "cancelled":
            return "已取消"
        if self.status == "failed":
            return self.errors[0] if self.errors else "备份失败"
        text = f"复制 {self.copied} 个文件"
        if self.skipped:
            text += f"，跳过 {self.skipped} 个未变化文件"
        if self.deleted:
            text += f"，清理 {self.deleted} 个多余文件"
        return text


class _Emitter:
    """节流进度回调，避免刷爆界面。"""

    def __init__(self, callback: Callable[[Progress], None] | None, interval: float = 0.08):
        self.callback = callback
        self.interval = interval
        self._last = 0.0
        self._last_percent = -1.0

    def __call__(self, progress: Progress, force: bool = False) -> None:
        if self.callback is None:
            return
        now = time.monotonic()
        percent = round(progress.percent, 1)
        if not force and now - self._last < self.interval and percent == self._last_percent:
            return
        self._last = now
        self._last_percent = percent
        try:
            self.callback(progress.copy())
        except Exception:
            pass


# ---------------------------------------------------------------- 过滤与遍历


def _matches(rel_posix: str, name: str, patterns: list[str]) -> bool:
    if not patterns:
        return False
    low_name = name.lower()
    low_rel = rel_posix.lower()
    for pattern in patterns:
        text = str(pattern).strip()
        if not text:
            continue
        pat = text.lower().replace("\\", "/")
        if pat.endswith("/"):
            pat = pat.rstrip("/")
        if fnmatch.fnmatchcase(low_name, pat):
            return True
        if fnmatch.fnmatchcase(low_rel, pat):
            return True
        if not pat.startswith("*/") and fnmatch.fnmatchcase(low_rel, "*/" + pat):
            return True
    return False


def normalize_exts(values) -> list[str]:
    """把 "zip, .7z" 之类的输入整理成 ['.zip', '.7z']。"""
    result: list[str] = []
    for raw in values or []:
        for piece in str(raw).replace("；", ";").replace("、", ",").replace(" ", ",").split(","):
            piece = piece.strip().lower()
            if not piece:
                continue
            for sub in piece.split(";"):
                sub = sub.strip().lower()
                if not sub:
                    continue
                if not sub.startswith("."):
                    sub = "." + sub
                if sub not in result:
                    result.append(sub)
    return result


def _ext_matches(name: str, exts: list[str]) -> bool:
    if not exts:
        return True
    low = name.lower()
    return any(low.endswith(ext) for ext in exts)


def iter_tree(
    root: Path,
    prefix: str,
    patterns: list[str],
    recursive: bool = True,
    errors: list[str] | None = None,
) -> Iterator[tuple[Path, str, int, float]]:
    """遍历目录，产出 (绝对路径, 目标相对路径, 大小, 修改时间)。

    ``errors`` 用于收集无法读取的目录/文件。调用方在镜像清理、还原等破坏性
    操作前必须检查它；不能把「读不到」当成「不存在」。
    """
    root_text = str(root)
    if os.name == "nt" and not root_text.startswith("\\\\?\\"):
        if root_text.startswith("\\\\"):
            scan_root = "\\\\?\\UNC\\" + root_text[2:]
        else:
            scan_root = "\\\\?\\" + os.path.abspath(root_text)
    else:
        scan_root = long_path(root_text)
    error_sink = errors if errors is not None else []

    def on_walk_error(exc: OSError) -> None:
        error_sink.append(f"{getattr(exc, 'filename', '') or root_text}: {exc}")

    for current, dirs, files in os.walk(scan_root, onerror=on_walk_error):
        if not recursive:
            dirs[:] = []
        try:
            current_rel = os.path.relpath(current, scan_root)
        except ValueError:
            current_rel = ""
        base = Path(current)
        kept = []
        for name in dirs:
            rel = name if current_rel in ("", ".") else f"{current_rel.replace(os.sep, '/')}/{name}"
            if not _matches(rel, name, patterns):
                kept.append(name)
        dirs[:] = kept

        for name in files:
            rel_inside = name if current_rel in ("", ".") else f"{current_rel.replace(os.sep, '/')}/{name}"
            if _matches(rel_inside, name, patterns):
                continue
            full = base / name
            try:
                stat = full.stat()
                size = stat.st_size
                mtime = stat.st_mtime
            except OSError as exc:
                error_sink.append(f"{rel_inside}: {exc}")
                continue
            yield full, prefix + rel_inside, size, mtime


def should_strip_root(sources: list[Path]) -> bool:
    """只有一个文件夹来源时，把它「内容」直接铺到目标根目录。"""
    return len(sources) == 1 and _path_is_dir(sources[0])


def iter_manifest(
    sources: list[Path],
    patterns: list[str],
    recursive: bool = True,
    errors: list[str] | None = None,
) -> Iterator[tuple[Path, str, int, float]]:
    strip = should_strip_root(sources)
    for source in sources:
        if _path_is_dir(source):
            prefix = "" if strip else source.name + "/"
            yield from iter_tree(source, prefix, patterns, recursive=recursive, errors=errors)
        elif _path_is_file(source):
            name = source.name
            if _matches(name, name, patterns):
                continue
            try:
                stat = source.stat()
                size, mtime = stat.st_size, stat.st_mtime
            except OSError as exc:
                if errors is not None:
                    errors.append(f"{name}: {exc}")
                continue
            yield source, name, size, mtime


def iter_source(source: Path, patterns: list[str]):
    """向后兼容：单目录遍历，产出 (绝对路径, 相对路径 posix, 大小)。"""
    for full, rel, size, _mtime in iter_tree(source, "", patterns):
        yield full, rel, size


# ---------------------------------------------------------------- 挑选


def collect_pick_candidates(
    sources: list[Path],
    patterns: list[str],
    task,
    cancel: threading.Event | None = None,
    progress_cb: Callable[[Progress], None] | None = None,
    errors: list[str] | None = None,
) -> list[tuple[Path, str, int, float]]:
    """按类型/时间过滤，再按规则挑出要备份的文件。"""
    exts = normalize_exts(task.pick_exts)
    cutoff = 0.0
    if int(task.pick_days or 0) > 0:
        cutoff = time.time() - int(task.pick_days) * 86400

    emit = _Emitter(progress_cb)
    progress = Progress(phase="pick", detail="正在查找符合条件的文件…")
    candidates: list[tuple[Path, str, int, float]] = []
    seen: dict[str, Path] = {}
    for index, (full, rel, size, mtime) in enumerate(
        iter_manifest(
            sources,
            patterns,
            recursive=bool(task.pick_recursive),
            errors=errors,
        )
    ):
        if index % 300 == 0:
            progress.detail = f"已扫描 {index} 个文件…"
            emit(progress)
            if cancel is not None and cancel.is_set():
                raise BackupCancelled
        if not _ext_matches(full.name, exts):
            continue
        if cutoff and mtime < cutoff:
            continue
        if rel in seen and seen[rel] != full:
            raise OSError(f"来源中存在同名目标路径：{rel}")
        seen[rel] = full
        candidates.append((full, rel, size, mtime))

    rule = task.pick_rule if task.pick_rule in ("newest", "largest", "all") else "newest"
    if rule == "newest":
        candidates.sort(key=lambda item: item[3], reverse=True)
    else:
        candidates.sort(key=lambda item: item[2], reverse=True)

    if rule != "all":
        limit = max(1, int(task.pick_count or 1))
        candidates = candidates[:limit]

    return candidates


# ---------------------------------------------------------------- 主流程


def prune_snapshots(target: Path, keep: int) -> int:
    """保留最新的 keep 个快照目录。"""
    if keep <= 0:
        return 0
    try:
        dirs = [d for d in target.iterdir() if d.is_dir() and SNAPSHOT_RE.match(d.name)]
    except OSError:
        return 0
    dirs.sort(key=lambda d: d.name, reverse=True)
    removed = 0
    for old in dirs[keep:]:
        shutil.rmtree(long_path(old), ignore_errors=True)
        removed += 1
    return removed


def _new_snapshot_dir(target: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate = target / stamp
    index = 1
    while candidate.exists():
        candidate = target / f"{stamp}-{index}"
        index += 1
    return candidate


def _same_file(src: Path, dst: Path) -> bool:
    try:
        if not dst.exists():
            return False
        a = src.stat()
        b = dst.stat()
        if a.st_size != b.st_size:
            return False
        return abs(a.st_mtime - b.st_mtime) < 2.0
    except OSError:
        return False


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _finish(result: Result, started: float) -> Result:
    result.duration = time.monotonic() - started
    result.ok = result.status in ("success", "partial")
    return result


def run_backup(
    task,
    settings,
    progress_cb: Callable[[Progress], None] | None = None,
    cancel: threading.Event | None = None,
) -> Result:
    """执行一次备份（镜像 / 快照 / 智能挑选）。"""
    started = time.monotonic()
    result = Result(status="failed")

    sources = task.source_paths()
    if not sources:
        result.errors.append("还没有选择要备份的文件或文件夹")
        return _finish(result, started)
    if not str(task.target or "").strip():
        result.errors.append("未设置备份目标目录")
        return _finish(result, started)

    missing = [s for s in sources if not _path_exists(s)]
    if missing:
        result.errors.append(f"找不到：{missing[0]}")
        return _finish(result, started)

    dst = Path(os.path.expandvars(os.path.expanduser(str(task.target))))
    try:
        dst_res = dst.resolve()
    except OSError:
        dst_res = dst

    for source in sources:
        try:
            src_res = source.resolve()
        except OSError:
            src_res = source
        if src_res == dst_res:
            result.errors.append("备份目标不能与来源相同")
            return _finish(result, started)
        if _path_is_dir(source) and _is_within(dst_res, src_res):
            result.errors.append(f"备份目标不能放在来源文件夹内部：{source}")
            return _finish(result, started)
        if _path_is_dir(source) and _is_within(src_res, dst_res):
            result.errors.append(f"来源文件夹不能位于备份目标内部：{source}")
            return _finish(result, started)

    patterns = task.effective_excludes(settings)

    try:
        Path(long_path(dst)).mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        result.errors.append(f"无法创建目标目录：{exc}")
        return _finish(result, started)

    if task.mode == "pick":
        return _run_pick(task, dst, sources, patterns, result, progress_cb, cancel, started)
    return _run_content(task, dst, sources, patterns, result, progress_cb, cancel, started)


def _run_content(
    task,
    dst: Path,
    sources: list[Path],
    patterns: list[str],
    result: Result,
    progress_cb,
    cancel,
    started: float,
) -> Result:
    emit = _Emitter(progress_cb)
    progress = Progress(phase="scan", detail="正在统计文件…")

    if task.mode == "snapshot":
        root = _new_snapshot_dir(dst)
        result.snapshot = root.name
    else:
        root = dst

    try:
        Path(long_path(root)).mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        result.errors.append(f"无法创建目标目录：{exc}")
        return _finish(result, started)
    result.dest = str(root)

    # 第一阶段：统计
    files: list[tuple[Path, str, int]] = []
    total_bytes = 0
    scan_errors: list[str] = []
    seen_paths: dict[str, Path] = {}
    try:
        for index, (full, rel, size, _mtime) in enumerate(
            iter_manifest(sources, patterns, errors=scan_errors)
        ):
            previous = seen_paths.get(rel)
            if previous is not None:
                if previous == full:
                    continue
                result.errors.append(
                    f"来源中存在同名目标路径，已停止以避免互相覆盖：\n{rel}"
                )
                return _finish(result, started)
            seen_paths[rel] = full
            files.append((full, rel, size))
            total_bytes += size
            if index % 300 == 0:
                progress.detail = f"正在统计文件… 已发现 {index} 个"
                progress.total_files = index
                emit(progress)
                if cancel is not None and cancel.is_set():
                    raise BackupCancelled
    except BackupCancelled:
        result.status = "cancelled"
        result.errors.append("用户取消了操作")
        return _finish(result, started)
    except OSError as exc:
        result.errors.append(f"读取来源失败：{exc}")
        return _finish(result, started)

    if scan_errors:
        result.errors.append(
            f"有 {len(scan_errors)} 个来源项无法读取，本次不会执行镜像清理："
            f"{scan_errors[0]}"
        )

    progress.phase = "copy"
    progress.total_files = len(files)
    progress.total_bytes = total_bytes
    progress.detail = f"共 {len(files)} 个文件，{human_size(total_bytes)}"
    emit(progress, force=True)

    # 第二阶段：复制
    errors: list[str] = []
    done_bytes = 0
    try:
        for index, (full, rel, size) in enumerate(files, start=1):
            if cancel is not None and cancel.is_set():
                raise BackupCancelled
            target = root / Path(rel)
            try:
                if _same_file(full, target):
                    result.skipped += 1
                else:
                    Path(long_path(target)).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(long_path(full), long_path(target))
                    result.copied += 1
                    result.bytes_copied += size
                    if len(result.files) < 40:
                        result.files.append(full.name)
            except OSError as exc:
                if len(errors) < 25:
                    errors.append(f"{rel}: {exc}")
            done_bytes += size
            progress.done_files = index
            progress.done_bytes = done_bytes
            progress.current = rel
            progress.detail = f"{index}/{len(files)}  {human_size(done_bytes)}"
            emit(progress)
    except BackupCancelled:
        result.status = "cancelled"
        result.errors = errors + ["用户取消了操作"]
        result.total_files = len(files)
        return _finish(result, started)

    # 第三阶段：镜像清理
    # 只有「来源扫描完整 + 有文件 + 目标扫描完整」才允许删除；
    # 任何读取失败都可能把有效备份误判为多余文件。
    if task.mode == "mirror" and task.delete_extraneous:
        target_errors: list[str] = []
        if scan_errors or not files:
            result.errors.append("来源扫描不完整或为空，已跳过镜像清理。")
        else:
            source_set = {rel for _f, rel, _s in files}
            deletions: list[tuple[Path, str]] = []
            try:
                for full, rel, _size, _mtime in iter_tree(
                    root, "", [], errors=target_errors
                ):
                    if rel in source_set:
                        continue
                    if _matches(rel, Path(rel).name, patterns):
                        continue
                    deletions.append((full, rel))
                if target_errors:
                    result.errors.append(
                        f"目标目录有 {len(target_errors)} 项无法读取，已跳过本次清理。"
                    )
                else:
                    for full, rel in deletions:
                        try:
                            os.remove(long_path(full))
                            result.deleted += 1
                        except OSError as exc:
                            target_errors.append(f"{rel}: {exc}")
                    if target_errors:
                        result.errors.append(
                            f"有 {len(target_errors)} 个多余文件无法删除，清理未完全完成。"
                        )
                    _prune_empty_dirs(root)
            except OSError as exc:
                result.errors.append(f"镜像清理失败：{exc}")

    # 第四阶段：清理旧快照
    if task.mode == "snapshot":
        prune_snapshots(dst, max(0, int(task.keep_versions or 0)))

    result.total_files = len(files)
    result.errors = errors + scan_errors[:20] + result.errors
    if errors and result.copied == 0:
        result.status = "failed"
    elif errors or scan_errors:
        result.status = "partial"
    else:
        result.status = "success"
    result.duration = time.monotonic() - started

    progress.phase = "done"
    progress.detail = result.summary
    emit(progress, force=True)
    return _finish(result, started)


def _run_pick(
    task,
    dst: Path,
    sources: list[Path],
    patterns: list[str],
    result: Result,
    progress_cb,
    cancel,
    started: float,
) -> Result:
    emit = _Emitter(progress_cb)
    scan_errors: list[str] = []
    try:
        candidates = collect_pick_candidates(
            sources,
            patterns,
            task,
            cancel=cancel,
            progress_cb=progress_cb,
            errors=scan_errors,
        )
    except BackupCancelled:
        result.status = "cancelled"
        result.errors.append("用户取消了操作")
        return _finish(result, started)
    except OSError as exc:
        result.status = "failed"
        result.errors.append(f"读取来源失败：{exc}")
        return _finish(result, started)

    if not candidates:
        result.status = "partial" if scan_errors else "success"
        result.note = "没有匹配的文件"
        result.errors = scan_errors[:20]
        result.dest = str(dst)
        return _finish(result, started)

    if task.pick_snapshot:
        root = _new_snapshot_dir(dst)
        result.snapshot = root.name
    else:
        root = dst
    try:
        Path(long_path(root)).mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        result.errors.append(f"无法创建目标目录：{exc}")
        return _finish(result, started)
    result.dest = str(root)

    progress = Progress(
        phase="copy",
        total_files=len(candidates),
        total_bytes=sum(c[2] for c in candidates),
        detail=f"挑中 {len(candidates)} 个文件",
    )
    emit(progress, force=True)

    errors: list[str] = []
    done_bytes = 0
    picked_names: list[str] = []
    try:
        for index, (full, rel, size, _mtime) in enumerate(candidates, start=1):
            if cancel is not None and cancel.is_set():
                raise BackupCancelled
            target = root / Path(rel)
            try:
                Path(long_path(target)).parent.mkdir(parents=True, exist_ok=True)
                if _same_file(full, target):
                    result.skipped += 1
                else:
                    shutil.copy2(long_path(full), long_path(target))
                    result.copied += 1
                    result.bytes_copied += size
                picked_names.append(full.name)
            except OSError as exc:
                if len(errors) < 25:
                    errors.append(f"{rel}: {exc}")
            done_bytes += size
            progress.done_files = index
            progress.done_bytes = done_bytes
            progress.current = rel
            progress.detail = f"{index}/{len(candidates)}  {human_size(done_bytes)}"
            emit(progress)
    except BackupCancelled:
        result.status = "cancelled"
        result.errors = errors + ["用户取消了操作"]
        result.total_files = len(candidates)
        return _finish(result, started)

    if task.pick_snapshot:
        prune_snapshots(dst, max(0, int(task.keep_versions or 0)))

    result.total_files = len(candidates)
    result.errors = errors + scan_errors[:20]
    result.files = list(picked_names)
    result.note = "挑中：" + "、".join(picked_names[:5])
    if len(picked_names) > 5:
        result.note += f" 等 {len(picked_names)} 个"
    if errors and result.copied == 0:
        result.status = "failed"
    elif errors or scan_errors:
        result.status = "partial"
    else:
        result.status = "success"
    result.duration = time.monotonic() - started

    progress.phase = "done"
    progress.detail = result.summary
    emit(progress, force=True)
    return _finish(result, started)


def _prune_empty_dirs(root: Path) -> None:
    for current, dirs, files in os.walk(str(root), topdown=False, onerror=lambda e: None):
        if not dirs and not files:
            try:
                os.rmdir(current)
            except OSError:
                pass


# ---------------------------------------------------------------- 还原


def plan_restore(source_dir, dest_dir, cancel: threading.Event | None = None) -> RestorePlan:
    """还原前统计文件、覆盖冲突和无法读取的项。"""
    src = Path(source_dir)
    dst = Path(dest_dir)
    plan = RestorePlan()
    if not _path_exists(src) or not _path_is_dir(src):
        plan.errors.append(f"备份目录不存在：{src}")
        return plan
    errors: list[str] = []
    for index, (full, rel, size, _mtime) in enumerate(
        iter_tree(src, "", [], errors=errors)
    ):
        if cancel is not None and cancel.is_set():
            plan.cancelled = True
            break
        plan.files += 1
        plan.total_bytes += size
        target = dst / Path(rel)
        try:
            if _path_exists(target):
                plan.conflicts += 1
        except OSError:
            plan.conflicts += 1
        if index % 300 == 0 and cancel is not None and cancel.is_set():
            plan.cancelled = True
            break
    plan.errors.extend(errors[:20])
    return plan


def restore_snapshot(
    source_dir,
    dest_dir,
    progress_cb: Callable[[Progress], None] | None = None,
    cancel: threading.Event | None = None,
    overwrite: bool = True,
) -> Result:
    """把备份目录内容还原到目标目录。

    ``overwrite=False`` 时保留目标中已存在的同名文件，并计入 skipped。
    """
    started = time.monotonic()
    emit = _Emitter(progress_cb)
    src = Path(source_dir)
    dst = Path(dest_dir)
    result = Result(status="failed", dest=str(dst))

    if not _path_exists(src) or not _path_is_dir(src):
        result.errors.append(f"备份目录不存在：{src}")
        return _finish(result, started)
    try:
        if _is_within(dst.resolve(), src.resolve()):
            result.errors.append("还原目标不能位于备份目录内部")
            return _finish(result, started)
    except OSError:
        pass

    progress = Progress(phase="scan", detail="正在扫描备份文件…")
    files: list[tuple[Path, str, int]] = []
    scan_errors: list[str] = []
    for index, (full, rel, size, _mtime) in enumerate(
        iter_tree(src, "", [], errors=scan_errors)
    ):
        files.append((full, rel, size))
        if index % 300 == 0:
            progress.detail = f"已发现 {index} 个文件"
            emit(progress)
            if cancel is not None and cancel.is_set():
                result.status = "cancelled"
                result.errors.append("用户取消了操作")
                return _finish(result, started)

    progress.phase = "copy"
    progress.total_files = len(files)
    progress.total_bytes = sum(f[2] for f in files)
    emit(progress, force=True)

    errors: list[str] = list(scan_errors[:20])
    done_bytes = 0
    try:
        for index, (full, rel, size) in enumerate(files, start=1):
            if cancel is not None and cancel.is_set():
                raise BackupCancelled
            target = dst / Path(rel)
            try:
                if _path_exists(target) and not overwrite:
                    result.skipped += 1
                else:
                    Path(long_path(target)).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(long_path(full), long_path(target))
                    result.copied += 1
                    result.bytes_copied += size
            except OSError as exc:
                if len(errors) < 25:
                    errors.append(f"{rel}: {exc}")
            done_bytes += size
            progress.done_files = index
            progress.done_bytes = done_bytes
            progress.current = rel
            progress.detail = f"{index}/{len(files)}"
            emit(progress)
    except BackupCancelled:
        result.status = "cancelled"
        result.errors = errors + ["用户取消了操作"]
        return _finish(result, started)

    result.total_files = len(files)
    result.errors = errors
    result.status = "partial" if errors and result.copied else ("failed" if errors else "success")
    result.duration = time.monotonic() - started

    progress.phase = "done"
    progress.detail = result.summary
    emit(progress, force=True)
    return _finish(result, started)


def list_snapshots(target) -> list[Path]:
    """列出某个任务目标目录下的快照（新到旧）。"""
    path = Path(target)
    if not _path_is_dir(path):
        return []
    try:
        items = [d for d in path.iterdir() if d.is_dir() and SNAPSHOT_RE.match(d.name)]
    except OSError:
        return []
    items.sort(key=lambda d: d.name, reverse=True)
    return items
