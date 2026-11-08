"""备份引擎与配置的自动化测试（无界面）。

运行：python tests\test_engine.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fk.backup import (  # noqa: E402
    list_snapshots,
    plan_restore,
    restore_snapshot,
    run_backup,
)
from fk.config import Config, Schedule, Settings, Task  # noqa: E402

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


def make_task(
    source,
    target: Path,
    mode: str = "mirror",
    keep: int = 3,
    delete_extraneous: bool = False,
) -> Task:
    sources = source if isinstance(source, (list, tuple)) else [source]
    return Task(
        id="t_test",
        name="测试任务",
        sources=[str(s) for s in sources],
        target=str(target),
        mode=mode,
        keep_versions=keep,
        delete_extraneous=delete_extraneous,
        schedule=Schedule(type="off"),
    )


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_mirror() -> None:
    print("\n[镜像备份]")
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        src = base / "src"
        dst = base / "dst"
        write(src / "a.txt", "hello")
        write(src / "sub" / "b.txt", "world")
        write(src / "cache.tmp", "temp")

        settings = Settings(excludes=["*.tmp"])
        task = make_task(src, dst)

        result = run_backup(task, settings)
        check(result.status == "success", f"首次备份成功（{result.summary}）")
        check((dst / "a.txt").exists(), "根目录文件已复制")
        check((dst / "sub" / "b.txt").exists(), "子目录文件已复制")
        check(not (dst / "cache.tmp").exists(), "排除规则生效（*.tmp 未复制）")
        check(result.copied == 2, f"复制数量正确（{result.copied}）")

        second = run_backup(task, settings)
        check(second.copied == 0, "再次备份无变化时不重复复制")
        check(second.skipped == 2, f"跳过数量正确（{second.skipped}）")

        time.sleep(0.05)
        write(src / "a.txt", "hello world, changed and longer")
        changed = run_backup(task, settings)
        check(changed.copied == 1, "修改后的文件被重新复制")
        check((dst / "a.txt").read_text(encoding="utf-8").startswith("hello world"), "内容已更新")


def test_mirror_delete() -> None:
    print("\n[镜像清理]")
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        src = base / "src"
        dst = base / "dst"
        write(src / "keep.txt", "1")
        write(src / "gone.txt", "2")
        settings = Settings(excludes=[])
        task = make_task(src, dst)
        run_backup(task, settings)
        check((dst / "gone.txt").exists(), "多余文件先被备份")

        (src / "gone.txt").unlink()
        task.delete_extraneous = True
        run_backup(task, settings)
        check(not (dst / "gone.txt").exists(), "开启清理后多余文件被删除")
        check((dst / "keep.txt").exists(), "源中仍存在的文件未被误删")


def test_mirror_scan_error_guard() -> None:
    print("\n[镜像清理：来源扫描不完整时不删除]")
    import fk.backup as backup_mod

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        src = base / "src"
        dst = base / "dst"
        write(src / "keep.txt", "1")
        write(dst / "should_stay.txt", "old backup")
        settings = Settings(excludes=[])
        task = make_task(src, dst, delete_extraneous=True)

        original = backup_mod.iter_manifest

        def fake_manifest(sources, patterns, recursive=True, errors=None):
            if errors is not None:
                errors.append("模拟：子目录读取失败")
            full = src / "keep.txt"
            yield full, "keep.txt", full.stat().st_size, full.stat().st_mtime

        backup_mod.iter_manifest = fake_manifest
        try:
            result = run_backup(task, settings)
        finally:
            backup_mod.iter_manifest = original
        check((dst / "should_stay.txt").exists(), "扫描不完整时目标旧文件保留")
        check(result.status == "partial", "扫描不完整标记为部分成功")
        check(any("镜像清理" in err for err in result.errors), "错误里说明跳过清理")


def test_source_collision() -> None:
    print("\n[多来源同名目标路径]")
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        first = base / "a" / "Photos"
        second = base / "b" / "Photos"
        write(first / "same.txt", "first")
        write(second / "same.txt", "second")
        dst = base / "dst"
        task = make_task([first, second], dst, delete_extraneous=False)
        result = run_backup(task, Settings(excludes=[]))
        check(result.status == "failed", "同名目标路径停止备份")
        check(any("同名目标路径" in err for err in result.errors), "给出同名提示")
        check(not (dst / "Photos" / "same.txt").exists(), "未发生静默覆盖")


def test_restore_conflicts() -> None:
    print("\n[还原冲突与跳过]")
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        src = base / "src"
        dst = base / "dst"
        out = base / "out"
        write(src / "x.txt", "new")
        write(src / "deep" / "y.txt", "nested")
        run_backup(make_task(src, dst, delete_extraneous=False), Settings(excludes=[]))
        write(out / "x.txt", "old")
        plan = plan_restore(dst, out)
        check(plan.files == 2, "还原检查统计文件")
        check(plan.conflicts == 1, "还原检查发现 1 个冲突")

        result = restore_snapshot(dst, out, overwrite=False)
        check((out / "x.txt").read_text(encoding="utf-8") == "old", "跳过同名文件")
        check(result.skipped >= 1, "跳过计数正确")
        check((out / "deep" / "y.txt").exists(), "不冲突文件仍还原")

        result2 = restore_snapshot(dst, out, overwrite=True)
        check((out / "x.txt").read_text(encoding="utf-8") == "new", "选择覆盖后更新")
        check(result2.status == "success", "覆盖还原成功")


def test_long_path() -> None:
    print("\n[超过 MAX_PATH 的来源]")
    from fk.fsutil import long_path

    base = Path(tempfile.mkdtemp(prefix="fk_long_"))
    try:
        deep = base / "src"
        while len(str(deep)) < 280:
            deep = deep / ("segment_" + str(len(str(deep))))
        os.makedirs(long_path(str(deep)))
        Path(long_path(str(deep))).joinpath("deep.txt").write_text("long", encoding="utf-8")
        dst = base / "dst"
        task = make_task(str(deep), dst, delete_extraneous=False)
        result = run_backup(task, Settings(excludes=[]))
        check(result.status == "success", f"长路径备份成功（{result.summary}）")
        check((dst / "deep.txt").exists(), "长路径文件复制到目标")
    finally:
        shutil.rmtree(long_path(str(base)), ignore_errors=True)


def test_snapshot() -> None:
    print("\n[时间戳快照]")
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        src = base / "src"
        dst = base / "dst"
        write(src / "doc.txt", "v1")
        settings = Settings(excludes=[])
        task = make_task(src, dst, mode="snapshot", keep=2)

        first = run_backup(task, settings)
        check(first.status == "success", "快照备份成功")
        check(bool(first.snapshot), f"生成快照目录：{first.snapshot}")

        time.sleep(1.1)
        write(src / "doc.txt", "v2")
        second = run_backup(task, settings)
        check(second.snapshot != first.snapshot, "两次快照目录不同")

        snapshots = list_snapshots(dst)
        check(len(snapshots) == 2, f"快照数量正确（{len(snapshots)}）")

        time.sleep(1.1)
        write(src / "doc.txt", "v3")
        run_backup(task, settings)
        snapshots = list_snapshots(dst)
        check(len(snapshots) == 2, "超出保留数量后旧快照被清理")

        newest = snapshots[0]
        check((newest / "doc.txt").read_text(encoding="utf-8") == "v3", "最新快照内容正确")


def test_restore() -> None:
    print("\n[还原]")
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        src = base / "src"
        dst = base / "dst"
        out = base / "restored"
        write(src / "x.txt", "restore me")
        write(src / "deep" / "y.txt", "nested")
        settings = Settings(excludes=[])
        task = make_task(src, dst, delete_extraneous=False)
        run_backup(task, settings)

        result = restore_snapshot(dst, out)
        check(result.status == "success", f"还原成功（{result.summary}）")
        check((out / "x.txt").read_text(encoding="utf-8") == "restore me", "文件内容一致")
        check((out / "deep" / "y.txt").exists(), "子目录结构保留")


def test_guards() -> None:
    print("\n[安全校验]")
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        src = base / "src"
        write(src / "a.txt", "1")
        settings = Settings(excludes=[])

        same = make_task(src, src)
        result = run_backup(same, settings)
        check(result.status == "failed", "目标与源相同时拒绝执行")

        inside = make_task(src, src / "backup")
        result = run_backup(inside, settings)
        check(result.status == "failed", "目标在源内部时拒绝执行")

        missing = make_task(base / "not-exists", base / "dst")
        result = run_backup(missing, settings)
        check(result.status == "failed", "源目录不存在时返回失败")


def test_config_roundtrip() -> None:
    print("\n[配置读写]")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.json"
        cfg = Config.load(path)
        task = make_task(Path(tmp) / "src", Path(tmp) / "dst")
        task.schedule = Schedule(type="weekly", time="03:30", weekdays=[1, 3, 5])
        cfg.add_task(task)
        cfg.settings.backup_root = str(Path(tmp) / "root")
        cfg.save()

        again = Config.load(path)
        check(len(again.tasks) == 1, "任务已持久化")
        check(again.tasks[0].schedule.type == "weekly", "计划类型持久化")
        check(again.tasks[0].schedule.weekdays == [1, 3, 5], "星期设置持久化")
        check(again.settings.backup_root.endswith("root"), "设置持久化")
        check(again.tasks[0].schedule.describe() == "每周一三五 03:30", "计划描述正确")

        legacy = Task.from_dict(
            {"id": "t_old", "name": "旧任务", "source": r"C:\Old", "target": r"D:\Old"}
        )
        check(legacy.sources == [r"C:\Old"], "1.0 版本的 source 字段已迁移到 sources")
        check(legacy.mode == "mirror", "旧任务默认使用镜像模式")


def test_recycle_bin() -> None:
    print("\n[回收站删除]")
    import threading

    from fk.fsutil import move_to_recycle_bin

    with tempfile.TemporaryDirectory() as tmp:
        victim = Path(tmp) / "filekeeper_recycle_test.txt"
        victim.write_text("bye", encoding="utf-8")
        error: dict = {}

        def work():
            try:
                move_to_recycle_bin([str(victim)])
            except Exception as exc:  # noqa: BLE001
                error["e"] = exc

        thread = threading.Thread(target=work)
        thread.start()
        thread.join(15)
        check(not error, f"后台线程调用回收站无异常（{error.get('e', 'ok')}）")
        check(not victim.exists(), "文件已从原位置移除")


def test_single_file() -> None:
    print("\n[单个文件备份]")
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        src = base / "report.xlsx"
        write(src, "spreadsheet")
        dst = base / "dst"
        settings = Settings(excludes=[])
        task = make_task(src, dst)
        result = run_backup(task, settings)
        check(result.status == "success", f"单文件备份成功（{result.summary}）")
        check((dst / "report.xlsx").exists(), "文件出现在目标根目录")
        check((dst / "report.xlsx").read_text(encoding="utf-8") == "spreadsheet", "内容一致")


def test_multi_sources() -> None:
    print("\n[多来源备份]")
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        src_a = base / "A"
        src_b = base / "B"
        single = base / "单独文件.txt"
        write(src_a / "a.txt", "a")
        write(src_b / "deep" / "b.txt", "b")
        write(single, "solo")
        dst = base / "dst"
        settings = Settings(excludes=[])
        task = make_task([src_a, src_b, single], dst)
        result = run_backup(task, settings)
        check(result.status == "success", f"多来源备份成功（{result.summary}）")
        check((dst / "A" / "a.txt").exists(), "文件夹 A 放进同名子目录")
        check((dst / "B" / "deep" / "b.txt").exists(), "文件夹 B 的结构被保留")
        check((dst / "单独文件.txt").exists(), "单独的文件放在目标根目录")
        check(result.copied == 3, f"复制数量正确（{result.copied}）")


def test_pick_mode() -> None:
    print("\n[智能挑选]")
    import os
    import time

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        src = base / "downloads"
        write(src / "old.zip", "a" * 10)
        write(src / "mid.zip", "b" * 100)
        write(src / "new.zip", "c" * 1000)
        write(src / "readme.txt", "not a zip")
        now = time.time()
        os.utime(src / "old.zip", (now - 3 * 86400, now - 3 * 86400))
        os.utime(src / "mid.zip", (now - 7200, now - 7200))
        os.utime(src / "new.zip", (now - 600, now - 600))

        settings = Settings(excludes=[])

        newest = make_task(src, base / "newest", mode="pick")
        newest.pick_exts = [".zip"]
        newest.pick_rule = "newest"
        newest.pick_count = 1
        result = run_backup(newest, settings)
        check(result.status == "success", f"挑选备份成功（{result.summary}）")
        check((base / "newest" / "new.zip").exists(), "「最新」挑中了 new.zip")
        check(not (base / "newest" / "old.zip").exists(), "未被挑中的文件没有复制")
        check(not (base / "newest" / "readme.txt").exists(), "类型过滤排除了非 zip 文件")
        check(bool(result.note), f"记录了挑选结果：{result.note}")

        largest = make_task(src, base / "largest", mode="pick")
        largest.pick_exts = ["zip"]  # 不带点也应能识别
        largest.pick_rule = "largest"
        largest.pick_count = 2
        run_backup(largest, settings)
        check((base / "largest" / "new.zip").exists(), "「最大」包含 new.zip")
        check((base / "largest" / "mid.zip").exists(), "「最大」包含 mid.zip")
        check(not (base / "largest" / "old.zip").exists(), "只保留前 2 个")

        everything = make_task(src, base / "all", mode="pick")
        everything.pick_exts = [".zip"]
        everything.pick_rule = "all"
        result = run_backup(everything, settings)
        copied = sorted(p.name for p in (base / "all").glob("*.zip"))
        check(copied == ["mid.zip", "new.zip", "old.zip"], f"「全部」复制了 3 个（{copied}）")

        days = make_task(src, base / "recent", mode="pick")
        days.pick_exts = [".zip"]
        days.pick_rule = "all"
        days.pick_days = 1
        run_backup(days, settings)
        remaining = sorted(p.name for p in (base / "recent").glob("*.zip"))
        check(
            remaining == ["mid.zip", "new.zip"],
            f"时间范围过滤生效（{remaining}）",
        )


def test_portable_paths() -> None:
    print("\n[便携化数据目录]")
    from fk import paths

    data = paths.data_dir()
    check(data.exists(), f"数据目录已创建：{data}")
    check(
        data.parent == paths.app_dir(),
        f"数据目录位于程序目录下（{data}）",
    )
    check(not str(data).upper().startswith("C:\\USERS"), "不再写入用户漫游目录")


def test_backup_log() -> None:
    print("\n[备份日志文件]")
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        src = base / "src"
        dst = base / "dst"
        write(src / "a.txt", "1")
        write(src / "b.txt", "2")
        settings = Settings(excludes=[])
        task = make_task(src, dst)
        cfg = Config.load(base / "config.json")
        cfg.add_task(task)

        result = run_backup(task, settings)
        cfg.record_result(task, result)
        log = dst / "备份日志.txt"
        check(log.exists(), "任务目录下生成了 备份日志.txt")
        text = log.read_text(encoding="utf-8-sig")
        check("成功" in text, "日志里包含备份结果")
        check("a.txt" in text and "b.txt" in text, "日志里包含备份文件名")

        write(src / "c.txt", "3")
        second = run_backup(task, settings)
        cfg.record_result(task, second)
        rows = [
            line
            for line in log.read_text(encoding="utf-8-sig").splitlines()
            if line.strip() and not line.startswith("#")
        ]
        check(len(rows) == 2, f"两次备份追加了两行（{len(rows)}）")
        check("c.txt" in rows[-1], "第二行记录了本次新增的文件")


def test_autostart() -> None:
    print("\n[开机自启注册表]")
    from fk import autostart

    name = "FileKeeperSelfTest"
    try:
        autostart.disable(name)
        check(not autostart.is_enabled(name), "初始状态未登记")
        check(autostart.enable(name), "写入启动项成功")
        check(autostart.is_enabled(name), "登记后能读到")
        command = autostart.current_command(name) or ""
        check("--minimized" in command, f"启动命令带 --minimized（{command[:60]}…）")
        check("main.py" in command or command.lower().endswith(".exe\""), "启动命令指向本程序")
        check(autostart.disable(name), "删除启动项成功")
        check(not autostart.is_enabled(name), "删除后读不到")
    finally:
        autostart.disable(name)


def test_autostart_failure() -> None:
    print("\n[开机自启删除失败]")
    from fk import autostart

    original = autostart._winreg

    class FakeWinreg:
        HKEY_CURRENT_USER = object()
        KEY_SET_VALUE = 1

        @staticmethod
        def OpenKey(*_args, **_kwargs):
            raise OSError("模拟权限不足")

    autostart._winreg = lambda: FakeWinreg
    try:
        check(autostart.disable("FileKeeperFailureTest") is False, "删除失败不再误报成功")
    finally:
        autostart._winreg = original


def test_uninstaller_guard() -> None:
    print("\n[卸载器不删除整个安装目录]")
    text = (ROOT / "installer" / "uninstall.bat").read_text(encoding="utf-8")
    check('rmdir /s /q "%DEST%"' not in text, "不再 rmdir 整个安装目录")
    check('rmdir /s /q "%DEST%\\data"' in text, "只清理专用 data 目录")
    check('rmdir /s /q "%DEST%\\_internal"' in text, "目录版会清理 _internal")
    check('rmdir "%DEST%" 2^>nul' in text, "只尝试删除空目录")


def main() -> int:
    print("=" * 60)
    print("电脑百宝箱 · 备份引擎自测")
    print("=" * 60)
    test_mirror()
    test_mirror_delete()
    test_mirror_scan_error_guard()
    test_source_collision()
    test_snapshot()
    test_restore()
    test_restore_conflicts()
    test_long_path()
    test_guards()
    test_config_roundtrip()
    test_recycle_bin()
    test_single_file()
    test_multi_sources()
    test_pick_mode()
    test_portable_paths()
    test_backup_log()
    test_autostart()
    test_autostart_failure()
    test_uninstaller_guard()
    print("\n" + "=" * 60)
    print(f"通过 {PASSED} 项，失败 {FAILED} 项")
    print("=" * 60)
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
