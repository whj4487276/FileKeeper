"""后台备份调度：单线程顺序执行队列中的任务。"""
from __future__ import annotations

import queue
import threading
import traceback

from . import backup as backup_mod
from .backup import Result


class BackupRunner:
    """把任务 id 放进队列，由单独的线程顺序执行。"""

    def __init__(self, config, events: "queue.Queue"):
        self.config = config
        self.events = events
        self._pending: list[dict] = []
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._cancel: threading.Event | None = None
        self.current_task_id: str | None = None
        self.running_ids: set[str] = set()

    # ------------------------------------------------------------ 对外接口
    def enqueue(self, task_ids: list[str], manual: bool = True) -> int:
        added = 0
        thread: threading.Thread | None = None
        with self._lock:
            for task_id in task_ids:
                if not self.config.get_task(task_id):
                    continue
                if task_id == self.current_task_id:
                    continue
                if any(item["id"] == task_id for item in self._pending):
                    continue
                self._pending.append({"id": task_id, "manual": manual})
                added += 1
                self.running_ids.add(task_id)
            if self._pending and self._thread is None:
                # 线程必须在锁内创建并挂到 _thread，避免两个并发 enqueue 各建一个
                self._thread = threading.Thread(
                    target=self._run, name="fk-backup", daemon=True
                )
                thread = self._thread
        if thread is not None:
            try:
                thread.start()
            except Exception:
                with self._lock:
                    if self._thread is thread:
                        self._thread = None
                raise
        return added

    def cancel(self) -> None:
        with self._lock:
            self._pending.clear()
            for task_id in list(self.running_ids):
                if task_id != self.current_task_id:
                    self.running_ids.discard(task_id)
            cancel = self._cancel
        if cancel is not None:
            cancel.set()

    def is_busy(self) -> bool:
        with self._lock:
            return bool(self._pending) or self._thread is not None

    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)

    # ------------------------------------------------------------ 工作线程
    def _run(self) -> None:
        while True:
            with self._lock:
                if not self._pending:
                    self._thread = None
                    self.current_task_id = None
                    self.events.put(("idle",))
                    return
                item = self._pending.pop(0)
            task_id = item["id"]
            manual = bool(item["manual"])
            task = self.config.get_task(task_id)
            if task is None:
                self.running_ids.discard(task_id)
                continue

            cancel_event = threading.Event()
            self.current_task_id = task_id
            with self._lock:
                self._cancel = cancel_event
            self.events.put(("start", task_id, task.name, manual))

            def on_progress(progress, _tid=task_id):
                self.events.put(("progress", _tid, progress))

            started = None
            try:
                started = __import__("time").monotonic()
                result = backup_mod.run_backup(
                    task,
                    self.config.settings,
                    progress_cb=on_progress,
                    cancel=cancel_event,
                )
            except Exception as exc:  # 兜底，避免线程直接崩掉
                result = Result(status="failed", errors=[f"内部错误：{exc}"])
                self.events.put(("log", f"{task.name}: {exc}\n{traceback.format_exc()}"))

            try:
                self.config.record_result(task, result)
            except Exception as exc:
                self.events.put(("log", f"保存记录失败：{exc}"))

            with self._lock:
                self.running_ids.discard(task_id)
                self.current_task_id = None
                self._cancel = None
            self.events.put(("done", task_id, result, manual))
