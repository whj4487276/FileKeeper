"""隐藏项选择器核心逻辑自测（目录枚举 / 隐藏与系统过滤）。

运行：python tests\\test_picker.py
"""
from __future__ import annotations

import ctypes
import os
import stat
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fk.ui import picker as picker_mod  # noqa: E402

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


def set_attr(path: Path, value: int) -> bool:
    try:
        return bool(ctypes.windll.kernel32.SetFileAttributesW(str(path), value))
    except Exception:
        return False


def test_scan() -> None:
    print("\n[目录枚举：隐藏 / 系统项]")
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        normal_dir = base / "normal_dir"
        normal_dir.mkdir()
        normal_file = base / "normal.txt"
        normal_file.write_text("normal", encoding="utf-8")
        dot_file = base / ".dot_hidden.txt"
        dot_file.write_text("dot", encoding="utf-8")
        hidden_file = base / "hidden_attr.txt"
        hidden_file.write_text("hidden", encoding="utf-8")
        hidden_dir = base / "hidden_dir"
        hidden_dir.mkdir()
        system_file = base / "system_attr.txt"
        system_file.write_text("system", encoding="utf-8")

        set_attr(hidden_file, 0x2)
        set_attr(hidden_dir, 0x2)
        set_attr(system_file, 0x4)
        try:
            entries, error = picker_mod.scan_directory(str(base))
            check(not error, f"目录可枚举（{error}）")
            by_name = {entry.name: entry for entry in entries}
            check(set(by_name) == {
                "normal_dir",
                "normal.txt",
                ".dot_hidden.txt",
                "hidden_attr.txt",
                "hidden_dir",
                "system_attr.txt",
            }, "隐藏项没有被枚举阶段过滤")
            check(by_name["normal_dir"].is_dir, "文件夹类型正确")
            check(not by_name["normal_dir"].hidden, "普通文件夹未标记隐藏")
            check(by_name[".dot_hidden.txt"].hidden, "点文件按隐藏项处理")
            check(by_name["hidden_attr.txt"].hidden, "HIDDEN 属性文件被识别")
            check(by_name["hidden_dir"].hidden, "HIDDEN 属性文件夹被识别")
            check(by_name["system_attr.txt"].system, "SYSTEM 属性文件被识别")

            normal_only = picker_mod.filter_entries(entries, False, False)
            names = {entry.name for entry in normal_only}
            check("normal.txt" in names and "normal_dir" in names, "普通项始终显示")
            check("hidden_attr.txt" not in names, "关闭隐藏项后 HIDDEN 文件隐藏")
            check(".dot_hidden.txt" not in names, "关闭隐藏项后点文件隐藏")
            check("system_attr.txt" not in names, "关闭系统项后 SYSTEM 文件隐藏")

            hidden_on = picker_mod.filter_entries(entries, True, False)
            names = {entry.name for entry in hidden_on}
            check("hidden_attr.txt" in names, "打开隐藏项后 HIDDEN 文件可见")
            check(".dot_hidden.txt" in names, "打开隐藏项后点文件可见")
            check("system_attr.txt" not in names, "系统项仍受系统开关控制")

            system_on = picker_mod.filter_entries(entries, False, True)
            names = {entry.name for entry in system_on}
            check("system_attr.txt" in names, "打开系统项后 SYSTEM 文件可见")
            check("hidden_attr.txt" not in names, "普通隐藏项不会因系统开关而可见")
        finally:
            for path in (hidden_file, hidden_dir, system_file):
                set_attr(path, 0x80)


def test_errors_and_paths() -> None:
    print("\n[错误处理与路径]")
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        file_path = base / "a.txt"
        file_path.write_text("x", encoding="utf-8")
        entries, error = picker_mod.scan_directory(str(base / "missing"))
        check(not entries and "不存在" in error, "不存在目录给出提示")
        entries, error = picker_mod.scan_directory(str(file_path))
        check(not entries and "文件" in error, "选中文件路径时提示不是文件夹")

    check(picker_mod.normalize_dir("C:") == "C:\\", "盘符补全为根路径")
    check(
        picker_mod.normalize_dir("子目录", "D:\\parent") == "D:\\parent\\子目录",
        "相对路径按当前目录解析",
    )
    drives = picker_mod.available_drives()
    check(bool(drives) and all(drive.endswith("\\") for drive in drives), "盘符列表可用")


def test_entries() -> None:
    print("\n[选择器条目]")
    entry = picker_mod.PickerEntry(
        name="a.txt",
        path="C:\\a.txt",
        is_dir=False,
        hidden=False,
        system=False,
        size=123,
    )
    check(entry.name == "a.txt" and entry.size == 123, "条目数据可用")
    check(
        picker_mod.PickerEntry("d", "C:\\d", True).is_dir,
        "文件夹条目类型正确",
    )


def main() -> int:
    print("=" * 60)
    print("电脑百宝箱 · 隐藏项选择器自测")
    print("=" * 60)
    test_scan()
    test_errors_and_paths()
    test_entries()
    print("\n" + "=" * 60)
    print(f"通过 {PASSED} 项，失败 {FAILED} 项")
    print("=" * 60)
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
