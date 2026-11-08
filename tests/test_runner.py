"""备份执行器串联与并发入队自测。

运行：python tests\\test_runner.py
"""
from __future__ import annotations

import queue
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fk import backup as backup_mod  # noqa: E402
from fk.backup import Result  # noqa: E402
from fk.config import Schedule, Settings, Task  # noqa: E402
from fk.runner import BackupRunner  # noqa: E402

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
    def __init__(self):
        self.tasks = [
            Task(id=f"t{i}", name=f"任务{i}", target="C:\\x", schedule=Schedule(type="off"))
            for i in range(6)
        ]
        self.results = []
        self.settings = Settings()

    def get_task(self, task_id):
        return next((t for t in self.tasks if t.id == task_id), None)

    def record_result(self, task, result):
        self.results.append((task.id, result.status))


def wait_idle(runner: BackupRunner, timeout: float = 5.0) -> None:
    end = time.time() + timeout
    while time.time() < end and runner.is_busy():
        time.sleep(0.01)


def main() -> int:
    print("=" * 60)
    print("电脑百宝箱 · 备份执行器自测")
    print("=" * 60)
    config = FakeConfig()
    events: queue.Queue = queue.Queue()
    runner = BackupRunner(config, events)
    active = 0
    max_active = 0
    lock = threading.Lock()
    original = backup_mod.run_backup

    def fake_run(task, settings, progress_cb=None, cancel=None):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return Result(status="success", copied=1, total_files=1)

    backup_mod.run_backup = fake_run
    try:
        barrier = threading.Barrier(2)

        def enqueue(ids):
            barrier.wait()
            runner.enqueue(ids)

        first = threading.Thread(target=enqueue, args=(["t0", "t1", "t2"],))
        second = threading.Thread(target=enqueue, args=(["t3", "t4", "t5"],))
        first.start()
        second.start()
        first.join()
        second.join()
        wait_idle(runner)
        check(max_active == 1, f"备份始终串行执行（最大并发 {max_active}）")
        check(len(config.results) == 6, f"六个任务都执行了（{len(config.results)}）")
        check(not runner.is_busy(), "队列结束后执行器空闲")
    finally:
        backup_mod.run_backup = original
        runner.cancel()

    print("\n" + "=" * 60)
    print(f"通过 {PASSED} 项，失败 {FAILED} 项")
    print("=" * 60)
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
