"""快捷键定义、校验、配置迁移与多热键注册调度自测。

运行：python tests\\test_hotkeys.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fk import hotkey as hk  # noqa: E402
from fk import hotkeys as hkm  # noqa: E402
from fk.config import CONFIG_VERSION, Config  # noqa: E402

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


def test_validation() -> None:
    print("\n[快捷键合法性]")
    check(hkm.validate_binding(0, ord("A")) is not None, "没有修饰键被拒绝")
    check(hkm.validate_binding(hk.MOD_CONTROL, 0) is not None, "没有主键被拒绝")
    check(
        "Esc" in (hkm.validate_binding(hk.MOD_CONTROL, hk.VK_ESCAPE) or ""),
        "Esc 主键被拒绝",
    )
    check(
        "Win+L" in (hkm.validate_binding(hk.MOD_WIN, ord("L")) or ""),
        "Win+L 被拒绝",
    )
    check(
        hkm.validate_binding(hk.MOD_WIN, hk.VK_TAB) is not None, "Win+Tab 被拒绝"
    )
    check(
        hkm.validate_binding(hk.MOD_CONTROL | hk.MOD_ALT, hk.VK_DELETE)
        is not None,
        "Ctrl+Alt+Del 被拒绝",
    )
    check(
        hkm.validate_binding(hk.MOD_ALT, hk.VK_TAB) is not None, "Alt+Tab 被拒绝"
    )
    check(
        hkm.validate_binding(hk.MOD_ALT, hk.VK_F4) is not None, "Alt+F4 被拒绝"
    )
    check(
        hkm.validate_binding(hk.MOD_CONTROL | hk.MOD_SHIFT, hk.VK_ESCAPE)
        is not None,
        "Ctrl+Shift+Esc 被拒绝",
    )
    check(
        hkm.validate_binding(hk.MOD_CONTROL, hk.VK_DELETE) is not None,
        "Delete 保留给清除绑定",
    )
    check(
        hkm.validate_binding(hk.MOD_CONTROL | hk.MOD_ALT, ord("A")) is None,
        "Ctrl+Alt+A 合法",
    )
    check(
        hkm.validate_binding(hk.MOD_CONTROL | hk.MOD_SHIFT, hk.VK_F9) is None,
        "Ctrl+Shift+F9 合法",
    )
    check(
        hkm.validate_binding(hk.MOD_CONTROL, hk.VK_LEFT) is None,
        "Ctrl+Left 合法",
    )

    check(
        hk.format_hotkey(hk.MOD_CONTROL | hk.MOD_ALT, ord("A")) == "Ctrl+Alt+A",
        "格式化顺序正确",
    )
    check(
        hk.parse_binding("Ctrl+Alt+A") == (hk.MOD_CONTROL | hk.MOD_ALT, ord("A")),
        "解析得到基础修饰键与 VK",
    )
    parsed = hk.parse_hotkey("Ctrl+Alt+A")
    check(
        parsed is not None and parsed[0] & hk.MOD_NOREPEAT,
        "旧接口带 NOREPEAT",
    )
    check(hk.parse_binding("A") is None, "纯主键被拒绝")
    check(hk.parse_binding("Ctrl+") is None, "缺少主键被拒绝")


def test_config_normalize() -> None:
    print("\n[快捷键配置规范化]")
    config, warnings = hkm.normalize_config(None)
    items = {item["action"]: item for item in config["items"]}
    check(len(items) == 3, "始终包含 3 个截图功能")
    check(
        items["capture.region"]["enabled"]
        and items["capture.region"]["vk"] == ord("A"),
        "区域截图默认 Ctrl+Alt+A",
    )
    check(not items["capture.fullscreen"]["enabled"], "全屏截图默认不启用")
    check(not items["capture.window"]["enabled"], "窗口截图默认不启用")
    check(not warnings, "全新配置没有警告")

    config, _ = hkm.normalize_config(None, legacy_hotkey="Alt+Shift+S")
    region = next(
        item for item in config["items"] if item["action"] == "capture.region"
    )
    check(
        region["modifiers"] == hk.MOD_CONTROL | hk.MOD_ALT
        and region["vk"] == ord("A"),
        "旧默认键迁移回 Ctrl+Alt+A",
    )

    config, warnings = hkm.normalize_config(
        {
            "version": 1,
            "items": [
                {
                    "action": "capture.region",
                    "modifiers": hk.MOD_CONTROL,
                    "vk": hk.VK_ESCAPE,
                    "enabled": True,
                },
                {
                    "action": "capture.fullscreen",
                    "modifiers": hk.MOD_CONTROL | hk.MOD_ALT,
                    "vk": ord("A"),
                    "enabled": True,
                },
                {
                    "action": "capture.window",
                    "modifiers": hk.MOD_CONTROL | hk.MOD_ALT,
                    "vk": ord("A"),
                    "enabled": True,
                },
                {"action": "unknown", "enabled": True},
            ],
        }
    )
    items = {item["action"]: item for item in config["items"]}
    check(not items["capture.region"]["enabled"], "非法 Esc 绑定降级为未启用")
    check(
        items["capture.fullscreen"]["enabled"],
        "重复组合保留第一个启用项",
    )
    check(not items["capture.window"]["enabled"], "重复组合的后来者被禁用")
    check(len(warnings) >= 2, f"记录了警告（{len(warnings)} 条）")

    exported = json.dumps(config, ensure_ascii=False)
    check("capture.region" in exported, "配置可导出 JSON")
    check(hkm.MAX_GLOBAL_HOTKEYS == 4, "全局热键上限为 4")

    import_config, _ = hkm.normalize_config(
        {
            "items": [
                {
                    "action": "capture.region",
                    "modifiers": hk.MOD_CONTROL | hk.MOD_ALT,
                    "vk": ord("A"),
                    "enabled": True,
                },
                {
                    "action": "capture.fullscreen",
                    "modifiers": hk.MOD_CONTROL | hk.MOD_ALT,
                    "vk": ord("A"),
                    "enabled": True,
                },
            ]
        },
        resolve_conflicts=False,
    )
    imported = {item["action"]: item for item in import_config["items"]}
    check(
        imported["capture.region"]["enabled"]
        and imported["capture.fullscreen"]["enabled"],
        "导入模式保留重复项，交给注册阶段提示替换",
    )


class FakeBackend:
    def __init__(self):
        self.active: dict[int, tuple[int, int]] = {}
        self.calls: list[tuple] = []
        self.fail_once: set[tuple[int, int]] = set()
        self.fail_always: set[tuple[int, int]] = set()
        self.next_id = 1

    def register(self, modifiers: int, vk: int) -> hkm.RegisterResult:
        key = (modifiers & hk.ALL_MODIFIERS, vk)
        self.calls.append(("register", key))
        if key in self.fail_once:
            self.fail_once.discard(key)
            return hkm.RegisterResult(False, 0, 1409)
        if key in self.fail_always:
            return hkm.RegisterResult(False, 0, 1409)
        hotkey_id = self.next_id
        self.next_id += 1
        self.active[hotkey_id] = key
        return hkm.RegisterResult(True, hotkey_id, 0)

    def unregister(self, hotkey_id: int) -> tuple[bool, int]:
        self.calls.append(("unregister", hotkey_id))
        if hotkey_id not in self.active:
            return False, 1419
        self.active.pop(hotkey_id, None)
        return True, 0


def test_registry() -> None:
    print("\n[多热键注册调度]")
    backend = FakeBackend()
    registry = hkm.HotkeyRegistry(backend)
    failures = registry.start()
    check(not failures, "默认只注册区域截图，无失败")
    region = registry.binding("capture.region")
    check(region.text == "Ctrl+Alt+A", "默认区域截图 Ctrl+Alt+A")
    check(
        registry.action_for_id(1) == "capture.region",
        "热键 ID 可映射回功能",
    )
    check(
        registry.state("capture.fullscreen").status == hkm.STATUS_DISABLED,
        "未设置的全屏截图是禁用状态",
    )

    # 修改：先注册新键，再注销旧键
    backend.calls.clear()
    result = registry.apply(
        "capture.region", hk.MOD_CONTROL | hk.MOD_SHIFT, hk.VK_F9
    )
    check(result.ok, "修改区域截图快捷键成功")
    check(
        registry.binding("capture.region").text == "Ctrl+Shift+F9",
        "绑定已更新",
    )
    register_pos = next(
        index for index, call in enumerate(backend.calls) if call[0] == "register"
    )
    unregister_pos = next(
        index for index, call in enumerate(backend.calls) if call[0] == "unregister"
    )
    check(
        register_pos < unregister_pos,
        "先注册新键、成功后再注销旧键（无空窗）",
    )
    check(1 not in backend.active, "旧键最终已注销")

    # 外部冲突：保留旧绑定
    old_text = registry.binding("capture.region").text
    backend.fail_always.add((hk.MOD_CONTROL | hk.MOD_ALT, ord("D")))
    result = registry.apply(
        "capture.region", hk.MOD_CONTROL | hk.MOD_ALT, ord("D")
    )
    check(not result.ok and result.external, "注册被占用时返回外部冲突")
    check("占用" in result.error, f"错误提示明确（{result.error}）")
    check(
        registry.binding("capture.region").text == old_text,
        "外部冲突时保持原绑定",
    )
    check(
        registry.state("capture.region").status == hkm.STATUS_ACTIVE
        and bool(registry.state("capture.region").error),
        "改键失败时旧键仍为已注册并带错误提示",
    )

    # 第一次绑定就失败：不得把新键保存为已启用
    backend.fail_always.add((hk.MOD_CONTROL, ord("X")))
    result = registry.apply("capture.window", hk.MOD_CONTROL, ord("X"))
    check(not result.ok and result.external, "首次绑定遇到外部冲突")
    check(
        registry.state("capture.window").status == hkm.STATUS_FAILED,
        "首次绑定失败标记为失败",
    )
    check(
        registry.binding("capture.window").vk == 0,
        "首次绑定失败不保存新键",
    )

    # 恢复可用绑定
    registry.apply(
        "capture.region", hk.MOD_CONTROL | hk.MOD_ALT, ord("A")
    )

    # 启用全屏截图
    result = registry.apply(
        "capture.fullscreen", hk.MOD_CONTROL | hk.MOD_ALT, ord("B")
    )
    check(result.ok, "全屏截图可绑定新快捷键")
    check(
        registry.state("capture.fullscreen").status == hkm.STATUS_ACTIVE,
        "全屏截图注册成功",
    )
    check(registry.enabled_count() == 2, "已启用数量为 2")

    # 内部冲突
    result = registry.apply(
        "capture.fullscreen", hk.MOD_CONTROL | hk.MOD_ALT, ord("A")
    )
    check(not result.ok, "内部重复绑定被拒绝")
    check(result.conflict_action == "capture.region", "提示具体冲突功能")
    check("区域截图" in result.error, "错误文案含功能名")

    # 替换对方绑定
    result = registry.apply(
        "capture.fullscreen",
        hk.MOD_CONTROL | hk.MOD_ALT,
        ord("A"),
        replace=True,
    )
    check(result.ok, "确认替换后成功")
    check(
        registry.state("capture.region").status == hkm.STATUS_DISABLED,
        "被替换的区域截图解除绑定",
    )
    check(
        registry.binding("capture.fullscreen").text == "Ctrl+Alt+A",
        "全屏截图使用替换后的键",
    )

    # 替换失败时回滚对方
    registry.apply(
        "capture.region", hk.MOD_CONTROL | hk.MOD_ALT, ord("B")
    )
    backend.fail_once.add((hk.MOD_CONTROL | hk.MOD_ALT, ord("A")))
    result = registry.apply(
        "capture.region",
        hk.MOD_CONTROL | hk.MOD_ALT,
        ord("A"),
        replace=True,
    )
    check(not result.ok, "替换时新键注册失败")
    check(
        registry.state("capture.fullscreen").status == hkm.STATUS_ACTIVE,
        "失败后对方已回滚注册",
    )
    check(
        registry.binding("capture.fullscreen").text == "Ctrl+Alt+A",
        "对方绑定保持不变",
    )

    # 禁用
    result = registry.disable("capture.fullscreen")
    check(result.ok, "可以禁用单个热键")
    check(
        registry.state("capture.fullscreen").status == hkm.STATUS_DISABLED,
        "禁用状态正确",
    )
    check(registry.enabled_count() == 1, "禁用项不占用启用名额")

    config = registry.config()
    check(
        config["items"][0]["action"] == "capture.region",
        "配置按固定顺序输出",
    )

    registry.stop()
    check(not backend.active, "退出时注销全部热键")


def test_config_persistence() -> None:
    print("\n[配置持久化与损坏回退]")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.json"
        cfg = Config.load(path)
        check(cfg.capture_hotkeys["items"][0]["vk"] == ord("A"), "新配置默认热键")
        cfg.set_capture_hotkeys(
            {
                "version": 1,
                "items": [
                    {
                        "action": "capture.region",
                        "modifiers": hk.MOD_CONTROL | hk.MOD_SHIFT,
                        "vk": hk.VK_F9,
                        "enabled": True,
                    },
                    {
                        "action": "capture.fullscreen",
                        "modifiers": hk.MOD_CONTROL | hk.MOD_ALT,
                        "vk": ord("B"),
                        "enabled": True,
                    },
                    {
                        "action": "capture.window",
                        "modifiers": 0,
                        "vk": 0,
                        "enabled": False,
                    },
                ],
            }
        )
        saved = json.loads(path.read_text(encoding="utf-8"))
        check(saved["version"] == CONFIG_VERSION, f"配置版本升到 {CONFIG_VERSION}")
        check(
            saved["screenshot_prefs"]["hotkey"] == "Ctrl+Shift+F9",
            "旧字段同步区域截图热键",
        )
        check(
            saved["capture_hotkeys"]["items"][0]["vk"] == hk.VK_F9,
            "新配置字段已落盘",
        )

        # 旧版配置迁移
        legacy = Path(tmp) / "legacy.json"
        legacy.write_text(
            json.dumps(
                {
                    "version": 3,
                    "screenshot_prefs": {"hotkey": "Alt+Shift+S"},
                }
            ),
            encoding="utf-8",
        )
        old = Config.load(legacy)
        check(
            old.capture_hotkeys["items"][0]["vk"] == ord("A"),
            "旧默认键迁移到 Ctrl+Alt+A",
        )

        # 损坏配置
        broken = Path(tmp) / "broken.json"
        broken.write_text("{ not json", encoding="utf-8")
        bad = Config.load(broken)
        check(bool(bad.load_error), "损坏配置被标记并回退")
        check(
            bad.capture_hotkeys["items"][0]["vk"] == ord("A"),
            "损坏配置仍有默认热键",
        )


def main() -> int:
    print("=" * 60)
    print("电脑百宝箱 · 快捷键自测")
    print("=" * 60)
    test_validation()
    test_config_normalize()
    test_registry()
    test_config_persistence()
    print("\n" + "=" * 60)
    print(f"通过 {PASSED} 项，失败 {FAILED} 项")
    print("=" * 60)
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
