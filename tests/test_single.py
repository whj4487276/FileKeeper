"""单实例控制自测（命名互斥体 + 唤起已有窗口）。

运行：python tests\\test_single.py
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fk import single  # noqa: E402

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


def test_mutex() -> None:
    print("\n[互斥体]")
    name = "Local\\FileKeeperTest_SingleInstance"
    first = single.SingleInstance(name)
    check(not first.already_running, "第一个实例判定为未运行")

    second = single.SingleInstance(name)
    check(second.already_running, "第二个实例判定为已在运行")
    second.release()

    third = single.SingleInstance(name)
    check(third.already_running, "第一个实例还持有互斥体，第三个也判定为已在运行")
    third.release()
    first.release()

    fresh = single.SingleInstance(name)
    check(not fresh.already_running, "全部释放后可以重新获得")
    fresh.release()


def test_activate() -> None:
    print("\n[唤起已有窗口]")
    # 当前没有窗口时不应该抛异常
    result = single.activate_existing("不存在的窗口标题 · 测试")
    check(isinstance(result, bool), f"未找到窗口时返回布尔值（{result}）")
    check(single.WM_SHOW_MAIN > 0x8000, "自定义消息号在 WM_APP 之后")
    check(single.TRAY_CLASS, "托盘窗口类名常量存在")


def test_constants() -> None:
    print("\n[常量]")
    check(single.MUTEX_NAME.startswith("Local\\"), "互斥体在会话内唯一（Local\\）")
    check(single.ERROR_ALREADY_EXISTS == 183, "ERROR_ALREADY_EXISTS 常量正确")


def main() -> int:
    print("=" * 60)
    print("电脑百宝箱 · 单实例自测")
    print("=" * 60)
    test_mutex()
    test_activate()
    test_constants()
    print("\n" + "=" * 60)
    print(f"通过 {PASSED} 项，失败 {FAILED} 项")
    print("=" * 60)
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
