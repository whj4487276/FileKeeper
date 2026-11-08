"""计时器核心逻辑自测（不依赖界面）。

运行：python tests\\test_timers.py
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fk import timers as tm  # noqa: E402

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


def test_format() -> None:
    print("\n[时间格式]")
    check(tm.format_hms(0) == "00:00:00", tm.format_hms(0))
    check(tm.format_hms(65) == "00:01:05", tm.format_hms(65))
    check(tm.format_hms(3661) == "01:01:01", tm.format_hms(3661))
    check(tm.format_hms(-5) == "00:00:00", "负数归零")
    check(tm.format_hms(tm.MAX_COUNT_SECONDS) == "99:59:59", "最大值显示 99:59:59")
    check(tm.parse_hms(1, 2, 3) == 3723, "解析 1:02:03")
    check(tm.parse_hms(0, 0, 0) == 0, "全 0")
    check(tm.parse_hms(99, 75, 75) == 99 * 3600 + 59 * 60 + 59, "分秒超限被夹紧")
    check(tm.split_hms(3723) == (1, 2, 3), "拆分正确")


def test_idle() -> None:
    print("\n[未开始]")
    t = tm.Timer(1)
    check(t.status == tm.STATUS_IDLE, "初始为空闲")
    check(t.display() == "00:00:00", "正计时未开始显示 00:00:00")
    check(t.button_text == "开始", "按钮为「开始」")
    check(not t.is_active, "不算工作中")

    d = tm.Timer(2, mode="down", duration=600)
    check(d.display() == "00:10:00", f"倒计时未开始显示设定时长（{d.display()}）")


def test_count_up() -> None:
    print("\n[正计时]")
    t = tm.Timer(1, title="正计时", mode="up")
    t.start(now=0.0)
    check(t.status == tm.STATUS_RUNNING, "开始后进入运行")
    check(t.is_active, "运行中 is_active")
    check(t.button_text == "停止", "运行中按钮为「停止」")
    check(t.display(now=65.0) == "00:01:05", f"65 秒后显示 {t.display(now=65.0)}")
    check(t.tick(now=100.0) is False, "正计时不会自动结束")

    t.stop()
    check(t.status == tm.STATUS_IDLE, "点停止回到空闲")
    check(t.display() == "00:00:00", "停止后归零")
    check(t.button_text == "开始", "停止后按钮为「开始」")

    t.start(now=500.0)
    check(t.display(now=505.0) == "00:00:05", "停止后再开始从 0 计")


def test_wrap() -> None:
    print("\n[正计时上限]")
    t = tm.Timer(1, mode="up")
    t.start(now=0.0)
    check(t.display(now=359999.0) == "99:59:59", "默认到 99:59:59")
    check(t.display(now=360000.0) == "00:00:00", "超过 99:59:59 立即归零")
    check(t.display(now=360001.0) == "00:00:01", "归零后继续计")

    limited = tm.Timer(2, mode="up", limit=60)
    limited.start(now=0.0)
    check(limited.display(now=59.0) == "00:00:59", "自定义上限内正常")
    check(limited.display(now=60.0) == "00:01:00", "到达自定义上限时显示上限值")
    check(limited.display(now=61.0) == "00:00:00", "超过上限立即归零")
    check(limited.display(now=62.0) == "00:00:01", "上限后继续计")

    top = tm.Timer(3, mode="up", limit=tm.MAX_COUNT_SECONDS)
    top.start(now=0.0)
    check(top.display(now=359999.0) == "99:59:59", "上限即最大值")
    check(top.display(now=360000.0) == "00:00:00", "最大值后归零")


def test_count_down() -> None:
    print("\n[倒计时]")
    t = tm.Timer(1, title="泡面", mode="down", duration=180, reminder="可以吃了")
    check(t.display() == "00:03:00", "未开始显示 03:00")
    t.start(now=0.0)
    check(t.button_text == "停止", "运行中按钮为「停止」")
    check(t.display(now=0.0) == "00:03:00", "开始瞬间显示总时长")
    check(t.display(now=60.0) == "00:02:00", "60 秒后剩 2 分钟")
    check(t.tick(now=170.0) is False, "没到点不算结束")
    check(t.tick(now=180.0) is True, "到点返回 True")
    check(t.status == tm.STATUS_IDLE, "结束后回到未开始状态")
    check(t.display(now=200.0) == "00:03:00", "结束后显示设定时长（不是 00:00:00）")
    check(t.button_text == "开始", "结束后按钮回到「开始」")
    check(t.tick(now=300.0) is False, "结束后不会重复触发")

    t.start(now=500.0)
    check(t.display(now=500.0) == "00:03:00", "再次开始重新从总时长倒数")

    t.stop()
    check(t.display() == "00:03:00", "停止后回到设定时长")


def test_independent() -> None:
    print("\n[互相独立]")
    a = tm.Timer(1, title="A")
    b = tm.Timer(2, title="B")
    c = tm.Timer(3, title="C", mode="down", duration=10)

    a.start(now=0.0)
    c.start(now=0.0)
    check(a.display(now=30.0) == "00:00:30", "A 在走")
    check(b.display(now=30.0) == "00:00:00", "B 未开始不受影响")
    check(c.display(now=30.0) == "00:00:00", "C 到点后显示 00:00:00")
    check(c.tick(now=30.0) is True, "C 到点由 tick 检测到结束")
    check(c.status == tm.STATUS_IDLE, "C 结束后回到未开始状态")
    check(c.display() == "00:00:10", "C 结束后显示设定时长")

    b.start(now=40.0)
    a.stop()
    check(b.display(now=50.0) == "00:00:10", "B 独立计时")
    check(a.display(now=60.0) == "00:00:00", "A 停止后归零")


def test_config() -> None:
    print("\n[配置读写]")
    items = [
        tm.Timer(1, title="泡面", mode="down", duration=180, reminder="可以吃了", sound=True).config(),
        tm.Timer(2, title="专注", mode="up", limit=1500).config(),
    ]
    loaded = tm.load_timers(items)
    check(len(loaded) == tm.MAX_TIMERS, f"固定 10 个（{len(loaded)}）")
    check(loaded[0].title == "泡面", "标题持久化")
    check(loaded[0].mode == "down" and loaded[0].duration == 180, "模式与时长持久化")
    check(loaded[0].reminder == "可以吃了", "提醒文字持久化")
    check(loaded[0].sound is True and loaded[1].sound is False, "声音报警开关持久化")
    check(loaded[1].limit == 1500, "正计时上限持久化")
    check(loaded[5].title == "计时器 6", "未配置的用默认标题")
    check(loaded[5].mode == "up" and loaded[5].limit == 0, "未配置的默认正计时、无上限")
    check(loaded[0].status == tm.STATUS_IDLE, "重启后一律空闲")


def test_apply() -> None:
    print("\n[修改设置]")
    t = tm.Timer(1)
    t.start(now=0.0)
    t.apply("新标题", "down", 60, 0, "到点了")
    check(t.title == "新标题", "标题更新")
    check(t.mode == "down" and t.duration == 60, "模式与时长更新")
    check(t.status == tm.STATUS_IDLE, "改设置会归零")
    check(t.display() == "00:01:00", "倒计时显示新时长")

    t.apply("", "up", 0, 90, "")
    check(t.title == "计时器 1", "空标题回退为默认")
    check(t.limit == 90, "上限更新")
    t.start(now=0.0)
    check(t.display(now=89.0) == "00:01:29", "上限内正常计数")
    check(t.display(now=90.0) == "00:01:30", "显示到上限值")
    check(t.display(now=91.0) == "00:00:00", "新上限生效")


def main() -> int:
    print("=" * 60)
    print("电脑百宝箱 · 计时器自测")
    print("=" * 60)
    test_format()
    test_idle()
    test_count_up()
    test_wrap()
    test_count_down()
    test_independent()
    test_config()
    test_apply()
    print("\n" + "=" * 60)
    print(f"通过 {PASSED} 项，失败 {FAILED} 项")
    print("=" * 60)
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
