"""时间提醒模块自测（不响铃、不弹窗）。

运行：python tests\test_alarm.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fk import alarm as al  # noqa: E402

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


def test_hms() -> None:
    print("\n[倒计时显示]")
    check(al.human_hms(0) == "00:00:00", al.human_hms(0))
    check(al.human_hms(9) == "00:00:09", al.human_hms(9))
    check(al.human_hms(3599) == "00:59:59", al.human_hms(3599))
    check(al.human_hms(3661) == "01:01:01", al.human_hms(3661))
    check(al.human_hms(90061) == "1 天 01:01:01", al.human_hms(90061))


def test_parse() -> None:
    print("\n[指定时间解析]")
    check(
        al.parse_datetime("2026-10-24", "08:30:15") == datetime(2026, 10, 24, 8, 30, 15),
        "日期 + 时分秒解析正确",
    )
    check(
        al.parse_datetime("2026-10-24", "08:30") == datetime(2026, 10, 24, 8, 30, 0),
        "只给时分时秒数为 0",
    )
    check(al.parse_datetime("2026/10/24", "08:30:00") is None, "错误日期格式返回 None")
    check(al.parse_datetime("2026-10-24", "25:00:00") is None, "非法小时返回 None")
    check(al.parse_datetime("2026-10-24", "08:70:00") is None, "非法分钟返回 None")
    check(al.parse_datetime("2026-10-24", "08:30:99") is None, "非法秒返回 None")


def test_plan() -> None:
    print("\n[提醒计划]")
    now = datetime.now()
    plan = al.make_alarm(now + timedelta(seconds=90), "countdown", True, False, "开会")
    check(plan["kind"] == "countdown", "记录了类型")
    check(plan["sound"] is True and plan["dialog"] is False, "记录了提醒方式")
    check(plan["label"] == "开会", "记录了备注")
    check(al.is_active(plan), "未来的提醒 → 有效")
    check(not al.is_active(None), "空计划 → 无效")

    past = al.make_alarm(now - timedelta(seconds=1), "clock")
    check(not al.is_active(past), "已过去的提醒 → 无效")

    left = al.seconds_left(now + timedelta(seconds=30), now=now)
    check(29 <= left <= 30, f"剩余秒数计算正确（{left}）")

    check(al.alarm_target(None) is None, "空计划没有目标时间")


def test_human_target() -> None:
    print("\n[目标时间描述]")
    today = al.human_target(datetime.now() + timedelta(seconds=30))
    check(today.startswith("今天"), today)
    tomorrow = al.human_target(datetime.now() + timedelta(days=1))
    check(tomorrow.startswith("明天"), tomorrow)


def test_repeat_countdown() -> None:
    print("\n[倒计时循环]")
    now = datetime(2026, 10, 24, 15, 20, 30)
    plan = al.make_alarm(
        now, "countdown", repeat="count", repeat_total=3, interval_seconds=60
    )
    nxt = al.next_target(plan, now)
    check(nxt == now + timedelta(seconds=60), f"下一次在 60 秒后（{nxt}）")

    plan["fired"] = 1
    check(al.next_target(plan, now) is not None, "已响 1 次（共 3 次）→ 继续")
    plan["fired"] = 2
    check(al.next_target(plan, now) is None, "已响 2 次、共 3 次 → 本次是最后一次，不再排下一轮")

    forever = al.make_alarm(
        now, "countdown", repeat="forever", interval_seconds=30
    )
    forever["fired"] = 999
    check(al.next_target(forever, now) == now + timedelta(seconds=30), "一直重复不受次数限制")

    plan["fired"] = 1
    stepped = al.advance(plan, now)
    check(stepped is not None and stepped["fired"] == 2, "advance 会累加已响次数")
    check(al.next_target(stepped, now) is None, "第 3 次响过之后结束")

    once = al.make_alarm(now, "countdown", repeat="none")
    check(al.next_target(once, now) is None, "不重复 → 结束")


def test_repeat_clock() -> None:
    print("\n[指定时间间隔]")
    now = datetime(2026, 10, 24, 15, 20, 30)

    daily = al.make_alarm(datetime(2026, 10, 24, 8, 0), "clock", repeat="daily")
    nxt = al.next_target(daily, now)
    check(nxt == datetime(2026, 10, 25, 8, 0), f"每天：下一次是明天 08:00（{nxt}）")

    hourly = al.make_alarm(now, "clock", repeat="hourly")
    nxt = al.next_target(hourly, now)
    check(nxt == datetime(2026, 10, 24, 16, 0, 0), f"每个整点：下一次 16:00（{nxt}）")

    hourly_off = al.make_alarm(now, "clock", repeat="hourly")
    nxt2 = al.next_target(hourly_off, datetime(2026, 10, 24, 16, 0, 0))
    check(nxt2 == datetime(2026, 10, 24, 17, 0, 0), "整点刚过 → 下一次是下一个整点")

    hour_min = al.make_alarm(now, "clock", repeat="hour_min", minute=5, second=15)
    nxt3 = al.next_target(hour_min, now)
    check(
        nxt3 == datetime(2026, 10, 24, 16, 5, 15),
        f"每小时 05:15：下一次 16:05:15（{nxt3}）",
    )
    nxt4 = al.next_target(hour_min, datetime(2026, 10, 24, 15, 0, 0))
    check(nxt4 == datetime(2026, 10, 24, 15, 5, 15), "整点后未到 05:15 → 本次小时内触发")


def test_window() -> None:
    print("\n[时间段限制]")
    now = datetime(2026, 10, 24, 17, 20, 30)
    plan = al.make_alarm(
        now,
        "clock",
        repeat="hourly",
        window_enabled=True,
        window_start="09:00",
        window_end="18:00",
    )
    check(al.next_target(plan, now) == datetime(2026, 10, 24, 18, 0, 0), "18:00 仍在窗口内")

    late = datetime(2026, 10, 24, 18, 30, 0)
    check(
        al.next_target(plan, late) == datetime(2026, 10, 25, 9, 0, 0),
        "18:00 之后 → 顺延到第二天 09:00",
    )

    check(al.in_window(datetime(2026, 10, 24, 9, 0), (9, 0), (18, 0)), "窗口起点算在内")
    check(al.in_window(datetime(2026, 10, 24, 18, 0), (9, 0), (18, 0)), "窗口终点算在内")
    check(not al.in_window(datetime(2026, 10, 24, 8, 59), (9, 0), (18, 0)), "窗口外不算")

    overnight = al.make_alarm(
        late,
        "clock",
        repeat="hourly",
        window_enabled=True,
        window_start="22:00",
        window_end="06:00",
    )
    check(
        al.next_target(overnight, datetime(2026, 10, 24, 23, 30)) == datetime(2026, 10, 25, 0, 0),
        "跨零点窗口：23:30 之后是次日 00:00",
    )
    check(
        al.next_target(overnight, datetime(2026, 10, 24, 7, 0)) == datetime(2026, 10, 24, 22, 0),
        "跨零点窗口：早上 07:00 顺延到 22:00",
    )


def main() -> int:
    print("=" * 60)
    print("电脑百宝箱 · 时间闹钟自测")
    print("=" * 60)
    test_hms()
    test_parse()
    test_plan()
    test_human_target()
    test_repeat_countdown()
    test_repeat_clock()
    test_window()
    print("\n" + "=" * 60)
    print(f"通过 {PASSED} 项，失败 {FAILED} 项")
    print("=" * 60)
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
