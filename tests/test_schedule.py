"""定时调度规则自测（纯逻辑，不启动线程）。

运行：python tests\\test_schedule.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fk.config import Schedule, Task  # noqa: E402
from fk.scheduler import Scheduler  # noqa: E402

PASSED = 0
FAILED = 0


def check(condition, message: str) -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  ok   {message}")
    else:
        FAILED += 1
        print(f"  FAIL {message}")


class FakeConfig:
    def __init__(self, tasks):
        self.tasks = tasks
        self.saved = 0

    def enabled_tasks(self):
        return list(self.tasks)

    def save(self):
        self.saved += 1
        return True


def make_task(
    schedule: Schedule,
    last_run: datetime | None = None,
    last_success: datetime | None = None,
    last_status: str = "",
) -> Task:
    task = Task(id="t", name="t", sources=[], target="", schedule=schedule)
    if last_run is not None:
        task.last_run = last_run.strftime("%Y-%m-%dT%H:%M:%S")
    if last_success is not None:
        task.last_success = last_success.strftime("%Y-%m-%dT%H:%M:%S")
    task.last_status = last_status
    return task


def make_scheduler(session_start: datetime, tasks=None) -> Scheduler:
    sched = Scheduler(FakeConfig(tasks or []), lambda _t: None)
    sched.session_start = session_start
    return sched


def daily(hour=22, minute=0) -> Schedule:
    return Schedule(type="daily", time=f"{hour:02d}:{minute:02d}")


def test_daily_normal() -> None:
    print("\n[每天：正常到点执行]")
    now = datetime(2026, 10, 23, 22, 30)
    sched = make_scheduler(datetime(2026, 10, 23, 8, 0))
    task = make_task(daily(), last_run=now - timedelta(days=1), last_success=now - timedelta(days=1))
    check(sched._is_due(task, now), "计划时间点软件在运行 → 到点后执行")


def test_daily_once_per_day() -> None:
    print("\n[每天：成功后一天只执行一次]")
    now = datetime(2026, 10, 23, 23, 40)
    sched = make_scheduler(datetime(2026, 10, 23, 8, 0))
    task = make_task(
        daily(),
        last_run=datetime(2026, 10, 23, 22, 3),
        last_success=datetime(2026, 10, 23, 22, 3),
        last_status="success",
    )
    check(not sched._is_due(task, now), "当天已经成功 → 不再重复")


def test_daily_wait_before_target() -> None:
    print("\n[每天：还没到点不执行]")
    now = datetime(2026, 10, 23, 9, 0)
    sched = make_scheduler(datetime(2026, 10, 23, 8, 0))
    task = make_task(daily(), last_success=datetime(2026, 10, 20, 22, 0))
    check(not sched._is_due(task, now), "09:00 时不会提前执行")


def test_daily_no_catch_up() -> None:
    print("\n[每天：错过后不自动补跑]")
    schedule = daily()
    # 22:00 的计划，22:02 才启动软件
    sched = make_scheduler(datetime(2026, 10, 23, 22, 2))
    task = make_task(schedule, last_success=datetime(2026, 10, 22, 22, 1))
    check(
        not sched._is_due(task, datetime(2026, 10, 23, 22, 12)),
        "启动时已过目标时间 → 不补跑",
    )
    # 跨午夜启动，也不补跑昨天
    late = make_scheduler(datetime(2026, 10, 24, 1, 0))
    check(
        not late._is_due(task, datetime(2026, 10, 24, 1, 0)),
        "跨午夜启动也不补跑前一天",
    )


def test_daily_failure_retry() -> None:
    print("\n[每天：失败退避后重试]")
    sched = make_scheduler(datetime(2026, 10, 23, 8, 0))
    task = make_task(
        daily(),
        last_run=datetime(2026, 10, 23, 22, 3),
        last_success=datetime(2026, 10, 22, 22, 0),
        last_status="failed",
    )
    check(
        not sched._is_due(task, datetime(2026, 10, 23, 22, 5)),
        "失败后 15 分钟内不重复入队",
    )
    check(
        sched._is_due(task, datetime(2026, 10, 23, 22, 20)),
        "超过退避时间后允许重试",
    )
    task.last_status = "cancelled"
    check(
        not sched._is_due(task, datetime(2026, 10, 23, 23, 0)),
        "用户取消后当天不再自动重试",
    )


def test_weekly() -> None:
    print("\n[每周]")
    schedule = Schedule(type="weekly", time="03:00", weekdays=[1])
    monday = datetime(2026, 10, 19, 3, 30)  # 2026-10-19 是周一
    sched = make_scheduler(datetime(2026, 10, 19, 0, 30))
    task = make_task(schedule, last_success=datetime(2026, 10, 12, 3, 0))
    check(sched._is_due(task, monday), "周一计划时间在运行 → 执行")

    wednesday = datetime(2026, 10, 21, 10, 0)
    check(not sched._is_due(task, wednesday), "非计划星期不执行")

    late_boot = make_scheduler(datetime(2026, 10, 19, 9, 0))
    check(
        not late_boot._is_due(task, datetime(2026, 10, 19, 9, 12)),
        "周一错过时间后启动 → 不补跑",
    )


def test_interval() -> None:
    print("\n[间隔]")
    sched = make_scheduler(datetime(2026, 10, 23, 0, 0))
    schedule = Schedule(type="interval", interval_min=60)
    task = make_task(
        schedule,
        last_run=datetime(2026, 10, 23, 10, 0),
        last_success=datetime(2026, 10, 23, 10, 0),
        last_status="success",
    )
    check(not sched._is_due(task, datetime(2026, 10, 23, 10, 30)), "30 分钟未到 → 不执行")
    check(sched._is_due(task, datetime(2026, 10, 23, 11, 1)), "超过 60 分钟 → 执行")

    failed = make_task(
        schedule,
        last_run=datetime(2026, 10, 23, 11, 0),
        last_success=datetime(2026, 10, 23, 9, 0),
        last_status="failed",
    )
    check(not sched._is_due(failed, datetime(2026, 10, 23, 11, 5)), "失败后 15 分钟内不重试")
    check(sched._is_due(failed, datetime(2026, 10, 23, 11, 20)), "失败退避后重试")


def test_off() -> None:
    print("\n[关闭]")
    sched = make_scheduler(datetime(2026, 10, 23, 0, 0))
    task = make_task(Schedule(type="off"))
    check(not sched._is_due(task, datetime(2026, 10, 23, 23, 0)), "关闭计划不执行")


def test_bootstrap() -> None:
    print("\n[新任务首次备份]")
    now = datetime(2026, 10, 23, 12, 0)
    task = Task(id="t", name="t", target="", schedule=Schedule(type="off"))
    task.bootstrap_at = (now - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%S")
    config = FakeConfig([task])
    fired = []
    sched = Scheduler(config, fired.append, tick_seconds=0.01)
    sched.session_start = now
    sched._check(now)
    check(fired == [task], "bootstrap 到点触发一次")
    check(task.bootstrap_at == "", "bootstrap 触发后清空")
    check(config.saved == 1, "bootstrap 触发后保存配置")
    sched._check(now)
    check(fired == [task], "bootstrap 只触发一次")

    future = Task(id="t2", name="t2", target="", schedule=Schedule(type="off"))
    future.bootstrap_at = (now + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%S")
    fired.clear()
    config2 = FakeConfig([future])
    sched2 = Scheduler(config2, fired.append, tick_seconds=0.01)
    sched2.session_start = now
    sched2._check(now)
    check(not fired, "bootstrap 未到点不触发")


def test_resume_detection() -> None:
    print("\n[休眠唤醒]")
    sched = Scheduler(FakeConfig([]), lambda _t: None)
    start = datetime(2026, 10, 23, 8, 0)
    sched.session_start = start
    sched.note_activity(start)
    sched.note_activity(start + timedelta(seconds=15))
    check(sched.session_start == start, "正常心跳不会重置会话起点")
    sched.note_activity(start + timedelta(hours=3))
    check(sched.session_start == start + timedelta(hours=3), "长时间空白视为休眠唤醒")


def test_default_backup_root() -> None:
    print("\n[默认主备份文件夹]")
    from fk.paths import backup_folder_name, default_backup_root, last_fixed_drive

    drive = last_fixed_drive()
    check(drive is not None and drive[1:2] == ":", f"找到固定磁盘：{drive}")
    root = default_backup_root()
    check(root.endswith(backup_folder_name()), f"目录名正确：{root}")
    check(root[1:3] == ":\\", "位于某个盘符根目录下")
    if drive:
        check(root.startswith(drive), f"使用最后一个盘符 {drive}")


def main() -> int:
    print("=" * 60)
    print("电脑百宝箱 · 定时规则自测")
    print("=" * 60)
    test_daily_normal()
    test_daily_once_per_day()
    test_daily_wait_before_target()
    test_daily_no_catch_up()
    test_daily_failure_retry()
    test_weekly()
    test_interval()
    test_off()
    test_bootstrap()
    test_resume_detection()
    test_default_backup_root()
    print("\n" + "=" * 60)
    print(f"通过 {PASSED} 项，失败 {FAILED} 项")
    print("=" * 60)
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
