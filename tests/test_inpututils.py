"""数字输入校验自测。

运行：python tests\\test_inpututils.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fk.inpututils import InputError, parse_int  # noqa: E402

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


def expect_error(value, label, minimum=None, maximum=None) -> None:
    try:
        parse_int(value, label, minimum, maximum)
    except InputError:
        check(True, f"{value!r} 被拒绝")
    else:
        check(False, f"{value!r} 应被拒绝")


def main() -> int:
    print("=" * 60)
    print("电脑百宝箱 · 数字输入校验自测")
    print("=" * 60)
    check(parse_int("10", "数量") == 10, "有效整数通过")
    check(parse_int(" 0 ", "数量", 0) == 0, "前后空格和 0 通过")
    expect_error("abc", "数量")
    expect_error("1.5", "数量")
    expect_error("", "数量")
    expect_error("-1", "数量", 0)
    expect_error("501", "数量", 0, 500)
    print("\n" + "=" * 60)
    print(f"通过 {PASSED} 项，失败 {FAILED} 项")
    print("=" * 60)
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
