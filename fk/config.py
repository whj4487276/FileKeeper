"""配置模型与持久化（JSON）。"""
from __future__ import annotations

import json
import os
import shutil
import threading
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import fsutil
from . import hotkeys as hotkeys_mod
from .hotkey import DEFAULT_HOTKEY, format_hotkey
from .paths import APP_VERSION, default_backup_root

CONFIG_VERSION = 5


def _safe_int(value, default: int = 0, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError):
        result = default
    if minimum is not None:
        result = max(minimum, result)
    if maximum is not None:
        result = min(maximum, result)
    return result


def _safe_float(value, default: float = 0.0, minimum: float | None = None) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        result = default
    if minimum is not None:
        result = max(minimum, result)
    return result


def _safe_bool(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("1", "true", "yes", "on"):
            return True
        if lowered in ("0", "false", "no", "off", ""):
            return False
    return default


def _safe_str(value, default: str = "") -> str:
    if value is None:
        return default
    try:
        return str(value)
    except Exception:
        return default


def _safe_str_list(value) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    result = []
    for item in value:
        text = _safe_str(item).strip()
        if text:
            result.append(text)
    return result


def _is_int_value(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _payload_warnings(data: dict) -> list[str]:
    """在安全降级之外，明确指出哪些字段类型不对，便于提示用户。"""
    warnings: list[str] = []
    settings = data.get("settings")
    if isinstance(settings, dict):
        for key, label in (
            ("keep_versions", "默认保留快照数"),
            ("log_retention", "历史保留数"),
        ):
            if key in settings and not _is_int_value(settings.get(key)):
                warnings.append(f"设置「{label}」不是整数，已使用默认值")
        if "excludes" in settings and not isinstance(settings.get("excludes"), list):
            warnings.append("默认排除规则不是列表，已使用默认值")
    tasks = data.get("tasks")
    if isinstance(tasks, list):
        for index, item in enumerate(tasks):
            if not isinstance(item, dict):
                continue
            for key, label in (
                ("keep_versions", "保留快照数"),
                ("pick_count", "挑选数量"),
                ("pick_days", "时间范围"),
                ("last_files", "上次文件数"),
                ("last_bytes", "上次字节数"),
            ):
                if key in item and not _is_int_value(item.get(key)):
                    warnings.append(f"任务「{item.get('name', index + 1)}」的「{label}」不是整数")
            schedule = item.get("schedule")
            if isinstance(schedule, dict):
                if "interval_min" in schedule and not _is_int_value(schedule.get("interval_min")):
                    warnings.append(f"任务「{item.get('name', index + 1)}」的间隔不是整数")
                if "weekdays" in schedule and not isinstance(schedule.get("weekdays"), list):
                    warnings.append(f"任务「{item.get('name', index + 1)}」的星期不是列表")
    history = data.get("history")
    if isinstance(history, list):
        for index, item in enumerate(history):
            if not isinstance(item, dict):
                continue
            for key in ("copied", "skipped", "deleted", "total_bytes"):
                if key in item and not _is_int_value(item.get(key)):
                    warnings.append(f"第 {index + 1} 条历史的「{key}」不是整数")
            if "duration" in item and not isinstance(item.get("duration"), (int, float)):
                warnings.append(f"第 {index + 1} 条历史的时长不是数字")
    return warnings


DEFAULT_EXCLUDES = [
    "$RECYCLE.BIN",
    "System Volume Information",
    "*.tmp",
    "*.temp",
    "*.bak",
    "~$*",
    "Thumbs.db",
    "desktop.ini",
    ".git",
    ".svn",
    "node_modules",
    "__pycache__",
]

MODE_LABELS = {
    "mirror": "镜像同步",
    "snapshot": "时间戳快照",
    "pick": "智能挑选",
}


@dataclass
class Schedule:
    type: str = "off"  # off | interval | daily | weekly
    interval_min: int = 60
    time: str = "22:00"
    weekdays: list[int] = field(default_factory=lambda: [1, 2, 3, 4, 5])

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "Schedule":
        data = data or {}
        raw_days = data.get("weekdays")
        if not isinstance(raw_days, (list, tuple)):
            raw_days = [1, 2, 3, 4, 5]
        days: list[int] = []
        for item in raw_days:
            day = _safe_int(item, 0)
            if 1 <= day <= 7 and day not in days:
                days.append(day)
        kind = _safe_str(data.get("type", "off"), "off")
        if kind not in ("off", "interval", "daily", "weekly"):
            kind = "off"
        return cls(
            type=kind,
            interval_min=_safe_int(data.get("interval_min", 60), 60, 1, 10080),
            time=_safe_str(data.get("time", "22:00"), "22:00"),
            weekdays=days or [1, 2, 3, 4, 5],
        )

    def describe(self) -> str:
        if self.type == "interval":
            return f"每 {self.interval_min} 分钟"
        if self.type == "daily":
            return f"每天 {self.time}"
        if self.type == "weekly":
            days = "".join(fsutil.weekday_name(d) for d in sorted(self.weekdays))
            return f"每周{days} {self.time}"
        return "关闭"


@dataclass
class Task:
    id: str
    name: str
    sources: list[str] = field(default_factory=list)
    target: str = ""
    mode: str = "mirror"  # mirror | snapshot | pick
    keep_versions: int = 5
    delete_extraneous: bool = False
    excludes: list[str] = field(default_factory=list)
    enabled: bool = True
    schedule: Schedule = field(default_factory=Schedule)

    # 智能挑选模式
    pick_exts: list[str] = field(default_factory=list)  # [".zip", ".rar"]
    pick_rule: str = "newest"  # newest | largest | all
    pick_count: int = 1
    pick_recursive: bool = True
    pick_days: int = 0  # 0 = 不限
    pick_snapshot: bool = False

    # 新任务提交后的一次性首次备份时间（ISO）；仅新建任务时写入
    bootstrap_at: str = ""

    last_run: str = ""
    last_status: str = ""
    last_success: str = ""
    last_files: int = 0
    last_bytes: int = 0
    last_duration: float = 0.0
    last_note: str = ""

    # ------------------------------------------------------------ 序列化
    def to_dict(self) -> dict:
        data = asdict(self)
        data["schedule"] = self.schedule.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Task":
        sources = _safe_str_list(data.get("sources"))
        if not sources:
            legacy = _safe_str(data.get("source")).strip()
            if legacy:
                sources = [legacy]
        mode = _safe_str(data.get("mode", "mirror"), "mirror")
        if mode not in MODE_LABELS:
            mode = "mirror"
        rule = _safe_str(data.get("pick_rule", "newest"), "newest")
        if rule not in ("newest", "largest", "all"):
            rule = "newest"
        last_run = _safe_str(data.get("last_run"))
        last_status = _safe_str(data.get("last_status"))
        last_success = _safe_str(data.get("last_success"))
        if not last_success and last_status == "success":
            # 旧版本只记录 last_run；成功的任务迁移为 last_success
            last_success = last_run
        return cls(
            id=_safe_str(data.get("id")) or new_id("t"),
            name=_safe_str(data.get("name"), "未命名任务"),
            sources=sources,
            target=_safe_str(data.get("target")),
            mode=mode,
            keep_versions=_safe_int(data.get("keep_versions", 5), 5, 0, 500),
            delete_extraneous=_safe_bool(data.get("delete_extraneous", False)),
            excludes=_safe_str_list(data.get("excludes")),
            enabled=_safe_bool(data.get("enabled", True), True),
            schedule=Schedule.from_dict(data.get("schedule")),
            pick_exts=_safe_str_list(data.get("pick_exts")),
            pick_rule=rule,
            pick_count=_safe_int(data.get("pick_count", 1), 1, 1, 9999),
            pick_recursive=_safe_bool(data.get("pick_recursive", True), True),
            pick_days=_safe_int(data.get("pick_days", 0), 0, 0, 36500),
            pick_snapshot=_safe_bool(data.get("pick_snapshot", False)),
            bootstrap_at=_safe_str(data.get("bootstrap_at")),
            last_run=last_run,
            last_status=last_status,
            last_success=last_success,
            last_files=_safe_int(data.get("last_files", 0), 0, 0),
            last_bytes=_safe_int(data.get("last_bytes", 0), 0, 0),
            last_duration=_safe_float(data.get("last_duration", 0.0), 0.0, 0.0),
            last_note=_safe_str(data.get("last_note")),
        )

    # ------------------------------------------------------------ 展示
    @property
    def mode_label(self) -> str:
        return MODE_LABELS.get(self.mode, self.mode)

    def sources_summary(self, limit: int = 0) -> str:
        if not self.sources:
            return "未设置"
        text = self.sources[0]
        if len(self.sources) > 1:
            text = f"{text} 等 {len(self.sources)} 项"
        if limit and len(text) > limit:
            head = limit // 2 - 2
            tail = limit - head - 3
            text = f"{text[:head]}…{text[-tail:]}"
        return text

    def pick_summary(self) -> str:
        exts = "、".join(self.pick_exts) if self.pick_exts else "所有文件"
        rule = {
            "newest": f"最新 {self.pick_count} 个",
            "largest": f"最大 {self.pick_count} 个",
            "all": "全部",
        }.get(self.pick_rule, "最新 1 个")
        return f"{exts} · {rule}"

    def effective_excludes(self, settings: "Settings") -> list[str]:
        seen: list[str] = []
        for item in list(settings.excludes) + list(self.excludes):
            item = str(item).strip()
            if item and item not in seen:
                seen.append(item)
        return seen

    def source_paths(self) -> list[Path]:
        result = []
        for item in self.sources:
            text = str(item).strip()
            if text:
                result.append(Path(os.path.expandvars(os.path.expanduser(text))))
        return result


@dataclass
class Settings:
    backup_root: str = field(default_factory=default_backup_root)
    excludes: list[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDES))
    keep_versions: int = 5
    delete_extraneous: bool = False
    notify: bool = True
    confirm_close: bool = True
    close_to_tray: bool = True
    start_minimized: bool = False
    tray_notify: bool = True
    auto_start: bool = False
    log_retention: int = 500

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "Settings":
        data = data if isinstance(data, dict) else {}
        return cls(
            backup_root=_safe_str(data.get("backup_root")) or default_backup_root(),
            excludes=_safe_str_list(data.get("excludes")) or list(DEFAULT_EXCLUDES),
            keep_versions=_safe_int(data.get("keep_versions", 5), 5, 0, 500),
            delete_extraneous=_safe_bool(data.get("delete_extraneous", False)),
            notify=_safe_bool(data.get("notify", True), True),
            confirm_close=_safe_bool(data.get("confirm_close", True), True),
            close_to_tray=_safe_bool(data.get("close_to_tray", True), True),
            start_minimized=_safe_bool(data.get("start_minimized", False)),
            tray_notify=_safe_bool(data.get("tray_notify", True), True),
            auto_start=_safe_bool(data.get("auto_start", False)),
            log_retention=_safe_int(data.get("log_retention", 500), 500, 50, 100000),
        )


@dataclass
class HistoryEntry:
    id: str
    task_id: str
    task_name: str
    time: str
    status: str
    mode: str
    copied: int = 0
    skipped: int = 0
    deleted: int = 0
    total_bytes: int = 0
    duration: float = 0.0
    dest: str = ""
    snapshot: str = ""
    error: str = ""
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "HistoryEntry":
        data = data if isinstance(data, dict) else {}
        return cls(
            id=_safe_str(data.get("id")) or new_id("h"),
            task_id=_safe_str(data.get("task_id")),
            task_name=_safe_str(data.get("task_name")),
            time=_safe_str(data.get("time")),
            status=_safe_str(data.get("status")),
            mode=_safe_str(data.get("mode"), "mirror"),
            copied=_safe_int(data.get("copied", 0), 0, 0),
            skipped=_safe_int(data.get("skipped", 0), 0, 0),
            deleted=_safe_int(data.get("deleted", 0), 0, 0),
            total_bytes=_safe_int(data.get("total_bytes", 0), 0, 0),
            duration=_safe_float(data.get("duration", 0.0), 0.0, 0.0),
            dest=_safe_str(data.get("dest")),
            snapshot=_safe_str(data.get("snapshot")),
            error=_safe_str(data.get("error")),
            note=_safe_str(data.get("note")),
        )

    @property
    def status_label(self) -> str:
        return {
            "success": "成功",
            "partial": "部分成功",
            "failed": "失败",
            "cancelled": "已取消",
        }.get(self.status, self.status or "—")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


class Config:
    """线程安全的配置容器。"""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.settings = Settings()
        self.tasks: list[Task] = []
        self.history: list[HistoryEntry] = []
        self.shutdown_plan: dict | None = None
        self.alarm: dict | None = None
        self.alarm_prefs: dict = {"sound": True, "dialog": True, "text": ""}
        self.timers: list[dict] = []
        self.capture_hotkeys, _warnings = hotkeys_mod.normalize_config(None)
        self.capture_hotkey_warnings: list[str] = []
        self.load_error: str = ""
        self.last_save_error: str = ""
        self.screenshot_prefs: dict = {
            "hotkey": DEFAULT_HOTKEY,
            "last_dir": "",
            "last_name": "",
        }

    # ------------------------------------------------------------ 载入 / 保存
    @classmethod
    def load(cls, path: Path) -> "Config":
        cfg = cls(path)
        if not cfg.path.exists():
            cfg.save()
            return cfg
        try:
            data = json.loads(cfg.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            cfg._backup_bad_config()
            cfg.load_error = f"配置文件损坏，已恢复默认设置：{exc}"
            return cfg
        if not isinstance(data, dict):
            cfg._backup_bad_config()
            cfg.load_error = "配置文件格式不正确，已恢复默认设置"
            return cfg

        warnings: list[str] = []
        warnings.extend(_payload_warnings(data))
        try:
            cfg.settings = Settings.from_dict(data.get("settings"))
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"设置读取失败，已使用默认值：{exc}")

        raw_tasks = data.get("tasks")
        tasks: list[Task] = []
        if isinstance(raw_tasks, list):
            for index, item in enumerate(raw_tasks):
                if not isinstance(item, dict):
                    warnings.append(f"第 {index + 1} 个任务格式无效，已跳过")
                    continue
                try:
                    tasks.append(Task.from_dict(item))
                except Exception as exc:  # noqa: BLE001
                    warnings.append(f"任务「{item.get('name', index + 1)}」读取失败，已跳过：{exc}")
        elif raw_tasks is not None:
            warnings.append("任务列表格式无效，已忽略")
        cfg.tasks = tasks

        raw_history = data.get("history")
        history: list[HistoryEntry] = []
        if isinstance(raw_history, list):
            for item in raw_history:
                if not isinstance(item, dict):
                    continue
                try:
                    history.append(HistoryEntry.from_dict(item))
                except Exception:
                    continue
        cfg.history = history

        raw_shutdown = data.get("shutdown")
        cfg.shutdown_plan = raw_shutdown if isinstance(raw_shutdown, dict) else None
        raw_alarm = data.get("alarm")
        cfg.alarm = raw_alarm if isinstance(raw_alarm, dict) else None
        raw_prefs = data.get("alarm_prefs")
        if isinstance(raw_prefs, dict):
            cfg.alarm_prefs = {
                "sound": _safe_bool(raw_prefs.get("sound", True), True),
                "dialog": _safe_bool(raw_prefs.get("dialog", True), True),
                "text": _safe_str(raw_prefs.get("text"))[:200],
            }
        raw_timers = data.get("timers")
        cfg.timers = (
            [t for t in raw_timers if isinstance(t, dict)] if isinstance(raw_timers, list) else []
        )
        raw_shot = data.get("screenshot_prefs")
        if isinstance(raw_shot, dict):
            cfg.screenshot_prefs = {
                "hotkey": _safe_str(raw_shot.get("hotkey"), DEFAULT_HOTKEY)[:40] or DEFAULT_HOTKEY,
                "last_dir": _safe_str(raw_shot.get("last_dir")),
                "last_name": _safe_str(raw_shot.get("last_name"))[:80],
            }

        raw_capture = data.get("capture_hotkeys")
        cfg.capture_hotkeys, cfg.capture_hotkey_warnings = hotkeys_mod.normalize_config(
            raw_capture if isinstance(raw_capture, dict) else None,
            legacy_hotkey=cfg.screenshot_prefs.get("hotkey"),
        )

        try:
            raw_version = int(data.get("version", 1) or 1)
        except (TypeError, ValueError):
            raw_version = 1
        needs_save = raw_version < CONFIG_VERSION
        if not isinstance(raw_capture, dict) or cfg.capture_hotkey_warnings:
            needs_save = True
        cfg._sync_legacy_hotkey()

        # 1.0 的默认备份目录在 C 盘用户目录下，升级时换成「最后一个盘符」的默认位置
        legacy_default = (Path.home() / "FileKeeperBackup").as_posix().lower()
        current = str(cfg.settings.backup_root or "").strip()
        if not current or Path(current).as_posix().lower() == legacy_default:
            cfg.settings.backup_root = default_backup_root()
            needs_save = True

        if warnings:
            cfg._backup_bad_config()
            cfg.load_error = "部分配置无效，已跳过损坏项：" + "；".join(warnings[:4])
            if len(warnings) > 4:
                cfg.load_error += f"；另有 {len(warnings) - 4} 项"
            needs_save = True
        if needs_save:
            cfg.save()  # 把旧版本结构升级后写回
        return cfg

    def _backup_bad_config(self) -> None:
        """保留一份损坏配置，避免修复/降级后无法追溯。"""
        try:
            target = self.path.with_name(self.path.name + ".bad")
            shutil.copy2(self.path, target)
        except OSError:
            pass

    def save(self) -> bool:
        with self.lock:
            payload = {
                "app": "FileKeeper",
                "version": CONFIG_VERSION,
                "app_version": APP_VERSION,
                "settings": self.settings.to_dict(),
                "tasks": [t.to_dict() for t in self.tasks],
                "history": [h.to_dict() for h in self.history],
                "shutdown": self.shutdown_plan,
                "alarm": self.alarm,
                "alarm_prefs": self.alarm_prefs,
                "timers": self.timers,
                "screenshot_prefs": self.screenshot_prefs,
                "capture_hotkeys": self.capture_hotkeys,
            }
            try:
                text = json.dumps(payload, ensure_ascii=False, indent=2)
            except (TypeError, ValueError) as exc:
                self.last_save_error = str(exc)
                return False
            tmp = self.path.with_suffix(".json.tmp")
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp.write_text(text, encoding="utf-8")
                os.replace(tmp, self.path)
                self.last_save_error = ""
                return True
            except (OSError, TypeError, ValueError) as exc:
                self.last_save_error = str(exc)
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
                return False

    # ------------------------------------------------------------ 任务
    def get_task(self, task_id: str) -> Task | None:
        with self.lock:
            for task in self.tasks:
                if task.id == task_id:
                    return task
        return None

    def add_task(self, task: Task) -> Task:
        with self.lock:
            self.tasks.append(task)
        self.save()
        return task

    def update_task(self, task: Task) -> None:
        with self.lock:
            for i, existing in enumerate(self.tasks):
                if existing.id == task.id:
                    self.tasks[i] = task
                    break
        self.save()

    def remove_task(self, task_id: str) -> None:
        with self.lock:
            self.tasks = [t for t in self.tasks if t.id != task_id]
        self.save()

    def enabled_tasks(self) -> list[Task]:
        with self.lock:
            return [t for t in self.tasks if t.enabled]

    # ------------------------------------------------------------ 历史
    def add_history(self, entry: HistoryEntry) -> None:
        with self.lock:
            self.history.insert(0, entry)
            limit = max(50, self.settings.log_retention)
            if len(self.history) > limit:
                self.history = self.history[:limit]

    def clear_history(self) -> None:
        with self.lock:
            self.history = []
        self.save()

    def record_result(self, task: Task, result) -> HistoryEntry:
        """把一次备份结果写回任务与历史。"""
        entry = HistoryEntry(
            id=new_id("h"),
            task_id=task.id,
            task_name=task.name,
            time=fsutil.now_iso(),
            status=result.status,
            mode=task.mode,
            copied=result.copied,
            skipped=result.skipped,
            deleted=result.deleted,
            total_bytes=result.bytes_copied,
            duration=result.duration,
            dest=result.dest,
            snapshot=result.snapshot,
            error="; ".join(result.errors[:3]),
            note=result.note,
        )
        with self.lock:
            target = self.get_task(task.id)
            if target is not None:
                target.last_run = entry.time
                target.last_status = result.status
                if result.status == "success":
                    target.last_success = entry.time
                    # 手动先跑成功后，新任务的一次性首次备份就无需再补
                    target.bootstrap_at = ""
                target.last_files = result.copied
                target.last_bytes = result.bytes_copied
                target.last_duration = result.duration
                target.last_note = result.note
            self.add_history(entry)
        self.save()

        # 追加任务目录下的「备份日志.txt」
        try:
            from . import audit

            audit.append_result(task, result, fsutil.parse_iso(entry.time))
        except Exception:
            pass
        return entry

    # ------------------------------------------------------------ 关机计划
    def set_shutdown(self, plan: dict | None) -> None:
        with self.lock:
            self.shutdown_plan = plan
        self.save()

    def clear_shutdown(self) -> None:
        self.set_shutdown(None)

    # ------------------------------------------------------------ 时间提醒
    def set_alarm(self, alarm: dict | None) -> None:
        with self.lock:
            self.alarm = alarm
        self.save()

    def clear_alarm(self) -> None:
        self.set_alarm(None)

    # ------------------------------------------------------------ 计时器
    def set_timers(self, items: list[dict]) -> None:
        with self.lock:
            self.timers = list(items)
        self.save()

    # ------------------------------------------------------------ 截图
    def _sync_legacy_hotkey(self) -> None:
        """把区域截图的热键同步到旧字段，兼容旧版界面/工具。"""
        if not isinstance(self.capture_hotkeys, dict):
            return
        for item in self.capture_hotkeys.get("items", []):
            if item.get("action") != "capture.region":
                continue
            vk = int(item.get("vk", 0) or 0)
            if vk:
                self.screenshot_prefs["hotkey"] = format_hotkey(
                    int(item.get("modifiers", 0) or 0), vk
                )[:40]
            else:
                self.screenshot_prefs["hotkey"] = ""
            return

    def capture_bindings(self) -> dict:
        return hotkeys_mod.bindings_from_config(self.capture_hotkeys)

    def set_capture_hotkeys(self, config: dict) -> list[str]:
        """保存新的快捷键配置，返回规范化过程中的警告。"""
        normalized, warnings = hotkeys_mod.normalize_config(config)
        with self.lock:
            self.capture_hotkeys = normalized
            self.capture_hotkey_warnings = list(warnings)
            self._sync_legacy_hotkey()
        self.save()
        return warnings

    def set_screenshot_prefs(self, **changes) -> None:
        with self.lock:
            prefs = dict(self.screenshot_prefs or {})
            prefs.update({k: v for k, v in changes.items() if v is not None})
            self.screenshot_prefs = prefs
        self.save()

    def set_alarm_prefs(self, sound: bool, dialog: bool, text: str) -> None:
        with self.lock:
            self.alarm_prefs = {
                "sound": bool(sound),
                "dialog": bool(dialog),
                "text": str(text or "")[:200],
            }
        self.save()

    def total_backup_bytes(self) -> int:
        with self.lock:
            tasks = list(self.tasks)
        total = 0
        for task in tasks:
            if not task.target:
                continue
            try:
                if not Path(task.target).exists():
                    continue
            except OSError:
                continue
            size, _count = fsutil.folder_size(task.target, limit=200000)
            total += size
        return total
