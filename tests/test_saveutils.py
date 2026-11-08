"""截图保存：命名、路径校验、原子写入与并发控制自测。

运行：python tests\\test_saveutils.py
"""
from __future__ import annotations

import os
import re
import stat
import sys
import tempfile
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fk import capture as cap  # noqa: E402
from fk import saveutils as su  # noqa: E402
from fk.paths import pictures_dir  # noqa: E402

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


def test_name() -> None:
    print("\n[自动命名]")
    name = su.default_screenshot_name(datetime(2026, 10, 31, 22, 4))
    check(name == "百宝箱20261031_2204", f"默认名称（{name}）")
    check(
        re.fullmatch(r"百宝箱\d{8}_\d{4}", su.default_screenshot_name()) is not None,
        "默认名称格式正确",
    )
    check(
        su.suggest_default_name(datetime(2026, 1, 2, 3, 4))
        == "百宝箱20260102_0304.png",
        "默认名称带 .png",
    )


def test_filename() -> None:
    print("\n[文件名合法性]")
    result = su.normalize_filename("截图")
    check(result.filename == "截图.png" and not result.error, "无扩展名自动补 .png")

    result = su.normalize_filename("截图.png")
    check(result.filename == "截图.png", ".png 保持")

    result = su.normalize_filename("截图.jpg")
    check(result.filename == "截图.png" and result.notes, "其他扩展名改为 .png 并提示")

    result = su.normalize_filename("截图.jpg.png")
    check(
        result.filename == "截图.png" and any(".jpg" in note for note in result.notes),
        "对话框补出的 .jpg.png 统一为 .png",
    )

    result = su.normalize_filename('a\\b/c:d*e?f"g<h>i|j')
    check(
        result.filename == "a_b_c_d_e_f_g_h_i_j.png",
        f"非法字符被替换（{result.filename}）",
    )
    check(result.notes, "非法字符有提示")

    result = su.normalize_filename("截图   ")
    check(result.filename == "截图.png", "末尾空格被去除")

    result = su.normalize_filename("截图...")
    check(result.filename == "截图.png", "末尾点被去除")

    for reserved in ("CON", "con", "PRN", "AUX", "NUL", "COM1", "COM9", "LPT1", "LPT9"):
        result = su.normalize_filename(reserved + ".png")
        check(bool(result.error), f"{reserved}.png 被拒绝")

    result = su.normalize_filename("CON.foo.png")
    check(bool(result.error), "CON.foo.png 也被拒绝")

    result = su.normalize_filename("")
    check(bool(result.error), "空文件名被拒绝")

    result = su.normalize_filename("截图 🎉")
    check(result.filename == "截图 🎉.png", "Unicode/emoji 保留")

    path, notes, error = su.normalize_save_path("C:\\temp\\截图")
    check(
        path is not None and path.name == "截图.png" and not error,
        "完整路径中的文件名被规范化",
    )


def test_network() -> None:
    print("\n[路径类型]")
    check(su.is_network_path("\\\\server\\share\\a.png"), "UNC 识别为网络路径")
    check(not su.is_network_path("C:\\Users\\a.png"), "本地路径不是网络路径")


def test_directory_and_file() -> None:
    print("\n[目录与目标文件校验]")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "shot.png"
        check(su.check_directory(path) is None, "可写目录通过校验")
        missing = Path(tmp) / "no" / "such" / "shot.png"
        check(su.check_directory(missing) is not None, "不存在目录被拒绝")

        readonly = Path(tmp) / "readonly.png"
        readonly.write_bytes(b"old")
        os.chmod(readonly, stat.S_IREAD)
        try:
            problem = su.check_target_file(readonly)
            check(problem is not None and "只读" in problem, "只读文件被拒绝")
        finally:
            os.chmod(readonly, stat.S_IWRITE)


def test_atomic_save() -> None:
    print("\n[原子写入]")
    image = cap.RawImage.blank(20, 12, (10, 20, 30))
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "shot.png"
        su.save_png_atomic(target, image)
        check(target.exists(), "文件已保存")
        check(target.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n", "内容是 PNG")
        leftovers = list(Path(tmp).glob(".fk_shot_*"))
        check(not leftovers, "成功后没有临时文件残留")

        canceled = Path(tmp) / "canceled.png"
        try:
            su.save_png_atomic(canceled, image, cancel_check=lambda: True)
            check(False, "取消时应抛出 SaveError")
        except su.SaveError as exc:
            check("取消" in exc.message, "取消保存被识别")
        check(not canceled.exists(), "取消后没有半成品")
        check(not list(Path(tmp).glob(".fk_shot_*")), "取消后没有临时文件")

        readonly = Path(tmp) / "readonly.png"
        readonly.write_bytes(b"old")
        os.chmod(readonly, stat.S_IREAD)
        try:
            try:
                su.save_png_atomic(readonly, image)
                check(False, "覆盖只读文件应失败")
            except su.SaveError as exc:
                check("只读" in exc.message or "权限" in exc.message, "只读文件保存失败提示")
        finally:
            os.chmod(readonly, stat.S_IWRITE)

        try:
            su.save_png_atomic(Path(tmp) / "missing" / "a.png", image)
            check(False, "不存在目录应失败")
        except su.SaveError as exc:
            check(bool(exc.message), "不存在目录有错误提示")

        original_png = su.cap_mod.save_png

        def full_disk(*_args, **_kwargs):
            raise OSError(28, "No space left on device")

        su.cap_mod.save_png = full_disk
        try:
            try:
                su.save_png_atomic(Path(tmp) / "full.png", image)
                check(False, "磁盘满应失败")
            except su.SaveError as exc:
                check("磁盘空间不足" in exc.message, "ENOSPC 提示磁盘空间不足")
        finally:
            su.cap_mod.save_png = original_png


def test_gate() -> None:
    print("\n[并发控制]")
    gate = su.SaveGate()
    check(gate.acquire(), "第一次获取保存锁成功")
    check(not gate.acquire(), "保存期间第二次获取失败")
    gate.release()
    check(gate.acquire(), "释放后可再次获取")
    gate.release()
    check(su.save_in_progress() is False, "空闲时没有保存任务")


def test_pictures_dir() -> None:
    print("\n[系统图片目录]")
    path = pictures_dir()
    check(isinstance(path, Path) and path.exists(), f"系统图片目录可用（{path}）")


def main() -> int:
    print("=" * 60)
    print("电脑百宝箱 · 截图保存自测")
    print("=" * 60)
    test_name()
    test_filename()
    test_network()
    test_directory_and_file()
    test_atomic_save()
    test_gate()
    test_pictures_dir()
    print("\n" + "=" * 60)
    print(f"通过 {PASSED} 项，失败 {FAILED} 项")
    print("=" * 60)
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
