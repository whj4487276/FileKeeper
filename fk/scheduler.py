"""定时备份调度器。

「每天 / 每周」的规则：
1. 到计划时间点时软件正在运行，才触发；
2. 软件启动时已经错过目标时间，不自动补跑（新任务可在提交时选择 5 分钟后先备份一次）；
3. 同一个计划时间点成功后不再重复；失败会隔一段时间重试。
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta

from .fsutil import parse_iso

# 失败后的重试间隔，避免调度器每 15 秒重复入队
RETRY_DELAY = timedelta(minutes=15)


class Scheduler(threading.Thread):
    """每 15 秒检查一次是否有任务到期。"""

    def __init__(self, config, on_due, tick_seconds: float = 15.0):
        super().__init__(name="fk-scheduler", daemon=True)
        self.config = config
        self.on_due = on_due
        self.tick = tick_seconds
        self._stop = threading.Event()
        self.session_start = datetime.now()
        self._last_tick: datetime | None = None
        self.last_error = ""

    # ------------------------------------------------------------ 生命周期
    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        while not self._stop.is_set():
            now = datetime.now()
            self.note_activity(now)
            try:
                self._check(now)
            except Exception as exc:  # noqa: BLE001 - 调度线程不能退出
                self.last_error = str(exc)
            self._stop.wait(self.tick)

    def note_activity(self, now: datetime) -> None:
        """检测休眠唤醒；唤醒后不补跑错过的每日/每周任务。"""
        if self._last_tick is not None:
            gap = (now - self._last_tick).total_seconds()
            if gap > max(90.0, self.tick * 5):
                self.session_start = now
        self._last_tick = now

    # ------------------------------------------------------------ 检查
    def _check(self, now: datetime) -> None:
        for task in self.config.enabled_tasks():
            try:
                bootstrap = parse_iso(getattr(task, "bootstrap_at", ""))
                if bootstrap is not None and now >= bootstrap:
                    task.bootstrap_at = ""
                    if hasattr(self.config, "save"):
                        self.config.save()
                    self.on_due(task)
                    continue
                if self._is_due(task, now):
                    self.on_due(task)
            except Exception as exc:  # noqa: BLE001
                self.last_error = str(exc)
                continue

    def _is_due(self, task, now: datetime) -> bool:
        sched = task.schedule
        if sched.type == "off":
            return False

        last_run = parse_iso(task.last_run)
        last_success = parse_iso(getattr(task, "last_success", ""))
        if last_success is None and task.last_status == "success":
            last_success = last_run

        if sched.type == "interval":
            minutes = max(1, int(sched.interval_min))
            if last_success is None:
                if last_run is not None and now - last_run < RETRY_DELAY:
                    return False
                return True
            if (
                last_run is not None
                and last_run >= last_success
                and task.last_status in ("failed", "partial")
                and now - last_run < RETRY_DELAY
            ):
                return False
            return (now - last_success) >= timedelta(minutes=minutes)

        if sched.type not in ("daily", "weekly"):
            return False

        if sched.type == "weekly" and now.isoweekday() not in (sched.weekdays or []):
            return False

        target = self._today_target(sched, now)
        if target is None:
            return False

        # 今天这个时间点已经成功备份过 —— 保证「一天只成功备份一次」
        if last_success is not None and last_success >= target:
            return False

        # 本次会话是在计划时间之后才开始的 → 已错过，不自动补跑
        if self.session_start > target:
            return False

        # 失败/部分成功后短暂退避，避免每 15 秒重试一次
        if (
            last_run is not None
            and last_run >= target
            and task.last_status in ("failed", "partial")
            and now - last_run < RETRY_DELAY
        ):
            return False
        if last_run is not None and last_run >= target and task.last_status == "cancelled":
            return False

        # 计划时间点软件一直在运行 → 立即执行
        return True

    @staticmethod
    def _today_target(sched, now: datetime) -> datetime | None:
        """今天（或今天之前最近一次）的计划时间；今天还没到点则返回 None。"""
        try:
            hour, minute = (int(x) for x in str(sched.time).split(":"))
        except (ValueError, TypeError):
            return None
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return None
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if now < target:
            return None
        return target
