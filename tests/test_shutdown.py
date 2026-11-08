"""定时关机模块自测（不执行真实关机）。

运行：python tests\test_shutdown.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fk import shutdown as sd  # noqa: E402

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


def test_targets() -> None:
    print("\n[目标时间计算]")
    now = datetime(2026, 10, 23, 15, 25)

    tomorrow = sd.tomorrow_at(8, 0, now=now)
    check(
        tomorrow == datetime(2026, 10, 24, 8, 0),
        f"明天 08:00 = {tomorrow}",
    )

    same_day, rolled = sd.today_at(8, 0, now=now)
    check(rolled and same_day == datetime(2026, 10, 24, 8, 0), "15:25 时「今天 08:00」顺延到明天")

    morning = datetime(2026, 10, 23, 7, 0)
    same_day2, rolled2 = sd.today_at(8, 0, now=morning)
    check(
        not rolled2 and same_day2 == datetime(2026, 10, 23, 8, 0),
        "07:00 时「今天 08:00」就是今天",
    )

    later = sd.after_delay(10, 0, now=now)
    check(later == now + timedelta(hours=10), f"10 小时后 = {later}")

    mixed = sd.after_delay(1, 30, now=now)
    check(mixed == now + timedelta(hours=1, minutes=30), "1 小时 30 分钟延时正确")


def test_parse() -> None:
    print("\n[时间解析]")
    value = sd.parse_datetime("2026-10-24", "08:00")
    check(value == datetime(2026, 10, 24, 8, 0), "指定日期时间解析正确")
    check(sd.parse_datetime("2026-10-24", "25:00") is None, "非法小时返回 None")
    check(sd.parse_datetime("2026/10/24", "08:00") is None, "错误格式返回 None")
    check(sd.parse_datetime("", "08:00") is None, "空日期返回 None")


def test_human() -> None:
    print("\n[文字描述]")
    check(sd.human_countdown(45) == "45 秒", sd.human_countdown(45))
    check(sd.human_countdown(125) == "2 分 5 秒", sd.human_countdown(125))
    check(sd.human_countdown(3725).startswith("1 小时 2 分"), sd.human_countdown(3725))
    check("天" in sd.human_countdown(90000), sd.human_countdown(90000))
    check(sd.human_target(datetime(2026, 10, 26, 8, 0)).endswith("08:00"), "目标时间带时刻")


def test_plan() -> None:
    print("\n[计划有效性]")
    now = datetime.now()
    plan = sd.make_plan(now + timedelta(hours=3), "custom_delay")
    check(plan["source"] == "custom_delay", "记录了来源")
    check(sd.plan_is_alive(plan), "未来时间 + 本次开机 → 有效")

    old = sd.make_plan(now - timedelta(minutes=1), "custom_delay")
    check(not sd.plan_is_alive(old), "时间已过 → 失效")

    other_boot = sd.make_plan(now + timedelta(hours=3), "custom_delay")
    other_boot["boot"] = "199901010000"
    check(not sd.plan_is_alive(other_boot), "换了开机周期（重启过）→ 失效")

    check(not sd.plan_is_alive(None), "空计划 → 失效")
    check(sd.plan_target(None) is None, "空计划没有目标时间")


def test_arm_mocked() -> None:
    print("\n[调用 shutdown.exe（已模拟）]")
    calls: list[list[str]] = []

    def fake_run(args, timeout=20):
        calls.append(list(args))
        return 0, ""

    original = sd._run
    sd._run = fake_run
    try:
        target = datetime.now() + timedelta(hours=10)
        ok, error = sd.arm(target, comment="测试")
        check(ok and error == "", "安排成功")
        check(all(not a.startswith("/a") for a in calls[0]), "默认不主动取消已有计划")
        check(calls[-1][0] == "/s" and calls[-1][1] == "/t", f"最终调用 /s /t（{calls[-1]}）")
        seconds = int(calls[-1][2])
        check(35700 <= seconds <= 36000, f"倒计时秒数正确（{seconds}）")
        check("/c" in calls[-1], "带上了关机提示语")

        calls.clear()
        ok_replace, _ = sd.arm(target, replace_existing=True)
        check(ok_replace and calls[0] == ["/a"], "明确要求替换时才先 /a")

        calls.clear()
        too_late = datetime.now() + timedelta(seconds=5)
        ok2, error2 = sd.arm(too_late)
        check(not ok2 and "太近" in error2, f"时间太近被拒绝（{error2}）")
        check(not calls, "被拒绝时没有调用 shutdown")

        calls.clear()
        ok3, _ = sd.cancel()
        check(ok3 and calls == [["/a"]], "取消只调用 /a")
    finally:
        sd._run = original


def test_cancel_when_idle() -> None:
    print("\n[没有计划时取消]")
    original = sd._run
    sd._run = lambda args, timeout=20: (1116, "无法中止系统关机，因为没有正在进行的关机。")
    try:
        ok, error = sd.cancel()
        check(ok and error == "", "没有计划时取消视为成功")
    finally:
        sd._run = original


def main() -> int:
    print("=" * 60)
    print("电脑百宝箱 · 定时关机自测")
    print("=" * 60)
    test_targets()
    test_parse()
    test_human()
    test_plan()
    test_arm_mocked()
    test_cancel_when_idle()
    print("\n" + "=" * 60)
    print(f"通过 {PASSED} 项，失败 {FAILED} 项")
    print("=" * 60)
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
