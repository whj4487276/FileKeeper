"""配置健壮性自测。

运行：python tests\\test_config.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fk.config import Config, Schedule, Settings, Task  # noqa: E402
from fk.timers import Timer, load_timers  # noqa: E402

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


def malformed_cases() -> list[tuple[str, dict]]:
    return [
        ("设置数值", {"settings": {"keep_versions": "abc"}}),
        ("任务数值", {"tasks": [{"id": "t1", "name": "x", "keep_versions": "abc"}]}),
        (
            "计划数值",
            {"tasks": [{"id": "t1", "name": "x", "schedule": {"interval_min": "abc"}}]},
        ),
        ("历史数值", {"history": [{"id": "h1", "copied": "abc"}]}),
        ("任务列表", {"tasks": "not-a-list"}),
    ]


def test_bad_types() -> None:
    print("\n[损坏字段不导致启动崩溃]")
    for label, payload in malformed_cases():
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            try:
                cfg = Config.load(path)
                check(True, f"{label} 可降级读取")
                check(bool(cfg.load_error), f"{label} 记录了读取警告")
                bad = path.with_name(path.name + ".bad")
                check(bad.exists(), f"{label} 保留了 .bad 备份")
            except Exception as exc:  # noqa: BLE001
                check(False, f"{label} 仍然崩溃：{type(exc).__name__}: {exc}")


def test_good_fields_and_migration() -> None:
    print("\n[字段迁移与往返]")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.json"
        payload = {
            "version": 4,
            "settings": {"keep_versions": 7, "excludes": ["*.tmp"]},
            "tasks": [
                {
                    "id": "t1",
                    "name": "旧任务",
                    "sources": ["C:\\x"],
                    "target": "D:\\y",
                    "last_run": "2026-10-23T22:00:00",
                    "last_status": "success",
                },
                {
                    "id": "t2",
                    "name": "新任务",
                    "sources": ["C:\\z"],
                    "target": "D:\\w",
                    "bootstrap_at": "2026-10-24T12:00:00",
                },
            ],
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
        cfg = Config.load(path)
        check(cfg.settings.keep_versions == 7, "设置字段读取正确")
        check(cfg.tasks[0].last_success == cfg.tasks[0].last_run, "旧成功任务迁移 last_success")
        check(cfg.tasks[1].bootstrap_at.endswith("12:00:00"), "bootstrap_at 保留")
        check(path.exists(), "配置文件仍存在")

        cfg.save()
        reloaded = Config.load(path)
        check(reloaded.tasks[1].bootstrap_at == cfg.tasks[1].bootstrap_at, "bootstrap_at 往返")
        check(not hasattr(reloaded.settings, "catch_up_default"), "旧补跑设置已移除")


def test_save_failure() -> None:
    print("\n[保存失败可见]")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Config(Path(tmp) / "config.json")
        original = os.replace
        os.replace = lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("模拟写盘失败"))
        try:
            ok = cfg.save()
            check(not ok, "save() 返回 False")
            check("模拟写盘失败" in cfg.last_save_error, "错误原因被记录")
        finally:
            os.replace = original


def test_timer_bad_values() -> None:
    print("\n[计时器损坏字段]")
    for data in ({"duration": "abc"}, {"limit": "abc"}, {"duration": None}):
        try:
            timer = Timer.from_config(1, data)
            check(timer.duration >= 1, f"计时器降级：{data}")
        except Exception as exc:  # noqa: BLE001
            check(False, f"计时器崩溃：{data} -> {exc}")
    timers = load_timers([{"duration": "abc"}, "bad", {"limit": "abc"}])
    check(len(timers) == 10, "损坏计时器列表仍生成 10 个")


def test_schedule_model() -> None:
    print("\n[计划模型]")
    schedule = Schedule.from_dict({"type": "daily", "interval_min": "abc"})
    check(schedule.type == "daily" and schedule.interval_min == 60, "非法间隔回退默认")
    check(not hasattr(schedule, "catch_up"), "计划已无补跑字段")
    settings = Settings.from_dict({"keep_versions": "abc"})
    check(settings.keep_versions == 5, "非法设置数值回退")
    task = Task.from_dict({"id": "x", "name": "x", "mode": "bad"})
    check(task.mode == "mirror", "非法模式回退")


def main() -> int:
    print("=" * 60)
    print("电脑百宝箱 · 配置健壮性自测")
    print("=" * 60)
    test_bad_types()
    test_good_fields_and_migration()
    test_save_failure()
    test_timer_bad_values()
    test_schedule_model()
    print("\n" + "=" * 60)
    print(f"通过 {PASSED} 项，失败 {FAILED} 项")
    print("=" * 60)
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
