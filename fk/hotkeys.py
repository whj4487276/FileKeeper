"""截图全局热键：功能定义、合法性校验、配置迁移与多热键注册调度。

每个功能最多一个全局热键；注册由 ``RegisterHotKey`` 仲裁，因此“是否被占用”
以操作系统返回的结果为准，不猜测占用者。
"""
from __future__ import annotations

import ctypes
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from . import hotkey as hk
from .paths import log_file

CONFIG_VERSION = 1
MAX_GLOBAL_HOTKEYS = 4
ERROR_HOTKEY_ALREADY_REGISTERED = 1409

STATUS_ACTIVE = "active"
STATUS_DISABLED = "disabled"
STATUS_FAILED = "failed"
STATUS_UNSET = "unset"

# 明确的系统保留组合；后续要扩充只需在这里加条目。
RESERVED_COMBOS: dict[tuple[int, int], str] = {
    (hk.MOD_WIN, ord("L")): "Win+L 是 Windows 锁屏快捷键",
    (hk.MOD_WIN, ord("D")): "Win+D 是显示桌面快捷键",
    (hk.MOD_WIN, ord("E")): "Win+E 是打开资源管理器快捷键",
    (hk.MOD_WIN, ord("R")): "Win+R 是打开运行对话框快捷键",
    (hk.MOD_WIN, hk.VK_TAB): "Win+Tab 是任务视图快捷键",
    (hk.MOD_CONTROL | hk.MOD_ALT, hk.VK_DELETE): "Ctrl+Alt+Del 是系统安全组合",
    (hk.MOD_ALT, hk.VK_TAB): "Alt+Tab 是切换窗口快捷键",
    (hk.MOD_CONTROL | hk.MOD_ALT, hk.VK_TAB): "Ctrl+Alt+Tab 是系统窗口切换快捷键",
    (hk.MOD_ALT, hk.VK_F4): "Alt+F4 是关闭窗口快捷键",
    (hk.MOD_CONTROL | hk.MOD_SHIFT, hk.VK_ESCAPE): "Ctrl+Shift+Esc 是任务管理器快捷键",
}


def log(message: str) -> None:
    """把热键相关异常写入 app.log（R-9.3）。"""
    try:
        with open(log_file(), "a", encoding="utf-8") as handle:
            handle.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}\n")
    except Exception:
        pass


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


@dataclass(frozen=True)
class HotkeyAction:
    id: str
    label: str
    default_modifiers: int
    default_vk: int
    description: str


ACTIONS: tuple[HotkeyAction, ...] = (
    HotkeyAction(
        "capture.region",
        "区域截图",
        hk.MOD_CONTROL | hk.MOD_ALT,
        ord("A"),
        "拖选一块区域后编辑/保存",
    ),
    HotkeyAction(
        "capture.fullscreen",
        "全屏截图",
        0,
        0,
        "截取整个虚拟屏幕（含多显示器）",
    ),
    HotkeyAction(
        "capture.window",
        "窗口截图",
        0,
        0,
        "截取当前前台窗口",
    ),
)
ACTION_BY_ID = {action.id: action for action in ACTIONS}


@dataclass
class HotkeyBinding:
    action: str
    modifiers: int = 0
    vk: int = 0
    enabled: bool = False

    @property
    def configured(self) -> bool:
        return bool(self.modifiers and self.vk)

    @property
    def text(self) -> str:
        if not self.vk:
            return ""
        return hk.format_hotkey(self.modifiers, self.vk)

    def clone(self) -> "HotkeyBinding":
        return HotkeyBinding(
            self.action, self.modifiers, self.vk, self.enabled
        )

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "modifiers": int(self.modifiers),
            "vk": int(self.vk),
            "enabled": bool(self.enabled),
        }


@dataclass
class BindingState:
    action: str
    binding: HotkeyBinding
    status: str = STATUS_DISABLED
    error: str = ""
    error_code: int = 0


@dataclass
class RegisterResult:
    ok: bool
    hotkey_id: int = 0
    error: int = 0


@dataclass
class ApplyResult:
    ok: bool
    error: str = ""
    error_code: int = 0
    conflict_action: str = ""
    external: bool = False


def default_binding(action_id: str) -> HotkeyBinding:
    action = ACTION_BY_ID.get(action_id)
    if action is None:
        raise KeyError(action_id)
    return HotkeyBinding(
        action.id,
        action.default_modifiers,
        action.default_vk,
        enabled=bool(action.default_vk),
    )


def default_bindings() -> dict[str, HotkeyBinding]:
    return {action.id: default_binding(action.id) for action in ACTIONS}


def validate_binding(modifiers: int, vk: int) -> str | None:
    """返回错误说明；合法时返回 None。"""
    modifiers = int(modifiers or 0) & hk.ALL_MODIFIERS
    vk = int(vk or 0)
    if not modifiers:
        return "至少需要一个修饰键（Ctrl / Alt / Shift / Win）"
    if not vk:
        return "请再按一个主键（字母、数字、F 键或方向键）"
    if vk == hk.VK_ESCAPE:
        return "Esc 保留给“取消录制”，不能绑定"
    if vk in (hk.VK_BACK, hk.VK_DELETE):
        return "Backspace / Delete 保留给“清除绑定”，不能绑定"
    if vk in (hk.VK_LWIN, hk.VK_RWIN):
        return "Win 键只能作为修饰键"
    allowed = (
        0x30 <= vk <= 0x39
        or 0x41 <= vk <= 0x5A
        or 0x70 <= vk <= 0x87
        or vk
        in (
            hk.VK_SPACE,
            hk.VK_TAB,
            hk.VK_RETURN,
            hk.VK_LEFT,
            hk.VK_RIGHT,
            hk.VK_UP,
            hk.VK_DOWN,
            hk.VK_HOME,
            hk.VK_END,
            hk.VK_PRIOR,
            hk.VK_NEXT,
            hk.VK_INSERT,
        )
    )
    if not allowed:
        return "不支持这个主键，请使用字母、数字、F 键、方向键或编辑键"
    reason = RESERVED_COMBOS.get((modifiers, vk))
    if reason:
        return f"{reason}，不能用于截图"
    return None


def _coerce_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_config(
    raw: dict | None,
    legacy_hotkey: str | None = None,
    resolve_conflicts: bool = True,
) -> tuple[dict, list[str]]:
    """把任意旧/新配置规范成 ``{version, items}``，返回 (配置, 警告列表)。"""
    warnings: list[str] = []
    bindings: dict[str, HotkeyBinding] = {}

    items = []
    if isinstance(raw, dict) and isinstance(raw.get("items"), list):
        items = raw["items"]

    for item in items:
        if not isinstance(item, dict):
            warnings.append("忽略了一个格式错误的快捷键条目")
            continue
        action_id = str(item.get("action", "") or "")
        action = ACTION_BY_ID.get(action_id)
        if action is None:
            warnings.append(f"忽略未知功能 ID：{action_id or '(空)'}")
            continue
        modifiers = _coerce_int(item.get("modifiers", 0)) & hk.ALL_MODIFIERS
        vk = _coerce_int(item.get("vk", 0))
        enabled = bool(item.get("enabled", False))
        if enabled and validate_binding(modifiers, vk):
            warnings.append(
                f"「{action.label}」的热键配置无效，已降级为未启用"
            )
            enabled = False
        if not enabled:
            bindings[action_id] = HotkeyBinding(action_id, modifiers, vk, False)
        else:
            bindings[action_id] = HotkeyBinding(action_id, modifiers, vk, True)

    if not bindings:
        # 从旧版 screenshot_prefs.hotkey 迁移；旧默认键统一回到 Ctrl+Alt+A
        legacy = str(legacy_hotkey or "")
        if legacy in hk.LEGACY_DEFAULT_HOTKEYS:
            legacy = hk.DEFAULT_HOTKEY
        parsed = hk.parse_binding(legacy)
        if parsed is not None:
            region = default_binding("capture.region")
            region.modifiers, region.vk = parsed
            region.enabled = True
            bindings[region.action] = region
        elif legacy:
            warnings.append("旧的截图快捷键无法识别，区域截图已降级为未启用")
            region = default_binding("capture.region")
            region.enabled = False
            bindings[region.action] = region
            for action in ACTIONS:
                bindings.setdefault(action.id, default_binding(action.id))

    for action in ACTIONS:
        if action.id not in bindings:
            bindings[action.id] = default_binding(action.id)

    # 同一组合只能绑定一个启用项：保留第一个，后面的降级为禁用
    seen: dict[tuple[int, int], str] = {}
    for action in ACTIONS:
        binding = bindings[action.id]
        if not binding.enabled or not binding.configured:
            continue
        key = (binding.modifiers, binding.vk)
        if key in seen:
            if resolve_conflicts:
                first = ACTION_BY_ID[seen[key]].label
                binding.enabled = False
                warnings.append(
                    f"「{action.label}」与「{first}」使用了相同快捷键，已降级为未启用"
                )
            else:
                warnings.append(
                    f"「{action.label}」与「{ACTION_BY_ID[seen[key]].label}」使用了相同快捷键"
                )
        else:
            seen[key] = action.id

    # 超过上限时禁用多余项（目前只有 3 个功能，保留兜底）
    enabled_items = [b for b in bindings.values() if b.enabled]
    if len(enabled_items) > MAX_GLOBAL_HOTKEYS:
        for binding in enabled_items[MAX_GLOBAL_HOTKEYS:]:
            binding.enabled = False
            warnings.append(
                f"全局热键超过 {MAX_GLOBAL_HOTKEYS} 个，已禁用「{ACTION_BY_ID[binding.action].label}」"
            )

    config = {
        "version": CONFIG_VERSION,
        "items": [bindings[action.id].to_dict() for action in ACTIONS],
    }
    return config, warnings


def bindings_from_config(raw: dict | None) -> dict[str, HotkeyBinding]:
    config, _warnings = normalize_config(raw)
    result: dict[str, HotkeyBinding] = {}
    for item in config.get("items", []):
        binding = HotkeyBinding(
            item["action"], item["modifiers"], item["vk"], item["enabled"]
        )
        result[binding.action] = binding
    return result


def config_from_bindings(bindings: dict[str, HotkeyBinding]) -> dict:
    return {
        "version": CONFIG_VERSION,
        "items": [
            bindings[action.id].to_dict()
            for action in ACTIONS
            if action.id in bindings
        ],
    }


class HotkeyRegistry:
    """管理所有截图功能的全局热键。

    ``backend`` 需提供：
    - ``register(modifiers, vk) -> RegisterResult``（成功时带唯一热键 ID）
    - ``unregister(hotkey_id) -> tuple[bool, int]``

    注册/注销失败都会写日志并保留原绑定，满足“修改失败旧键仍可用”。
    """

    def __init__(
        self,
        backend,
        config: dict | None = None,
        legacy_hotkey: str | None = None,
        on_change: Callable[[], None] | None = None,
    ):
        self._backend = backend
        self._on_change = on_change
        self._config, self.warnings = normalize_config(config, legacy_hotkey)
        self._bindings = bindings_from_config(self._config)
        self._states: dict[str, BindingState] = {}
        self._active: dict[str, int] = {}
        self._id_actions: dict[int, str] = {}
        for action in ACTIONS:
            binding = self._bindings[action.id]
            self._states[action.id] = BindingState(
                action.id,
                binding,
                STATUS_DISABLED if not binding.enabled else STATUS_UNSET,
            )

    # ------------------------------------------------------------ 查询
    @property
    def warnings_list(self) -> list[str]:
        return list(self.warnings)

    def binding(self, action_id: str) -> HotkeyBinding:
        return self._bindings[action_id]

    def state(self, action_id: str) -> BindingState:
        return self._states[action_id]

    def states(self) -> list[BindingState]:
        return [self._states[action.id] for action in ACTIONS]

    def enabled_count(self) -> int:
        return sum(
            1
            for b in self._bindings.values()
            if b.enabled and b.configured
        )

    def active_count(self) -> int:
        return len(self._active)

    def action_for_id(self, hotkey_id: int) -> str | None:
        return self._id_actions.get(int(hotkey_id))

    def find_conflict(
        self, action_id: str, modifiers: int, vk: int
    ) -> str | None:
        key = (int(modifiers) & hk.ALL_MODIFIERS, int(vk))
        for action in ACTIONS:
            if action.id == action_id:
                continue
            binding = self._bindings[action.id]
            if binding.enabled and binding.configured:
                if (binding.modifiers, binding.vk) == key:
                    return action.id
        return None

    def config(self) -> dict:
        return config_from_bindings(self._bindings)

    def failures(self) -> list[BindingState]:
        return [
            state
            for state in self.states()
            if state.status == STATUS_FAILED
        ]

    # ------------------------------------------------------------ 启动 / 停止
    def start(self) -> list[BindingState]:
        """注册所有已启用项；返回失败项。"""
        self._unregister_all()
        failures: list[BindingState] = []
        for action in ACTIONS:
            binding = self._bindings[action.id]
            state = self._states[action.id]
            state.error = ""
            state.error_code = 0
            if not binding.enabled:
                state.status = STATUS_DISABLED
                continue
            if not binding.configured:
                state.status = STATUS_UNSET
                continue
            result = self._register(binding)
            if result.ok:
                self._active[action.id] = result.hotkey_id
                self._id_actions[result.hotkey_id] = action.id
                state.status = STATUS_ACTIVE
            else:
                state.status = STATUS_FAILED
                state.error_code = result.error
                state.error = self._external_message(result.error)
                failures.append(state)
                log(
                    f"注册截图热键失败 action={action.id} "
                    f"key={binding.text} error={result.error}"
                )
        self._emit()
        return failures

    def stop(self, quiet: bool = False) -> None:
        self._unregister_all()
        if not quiet:
            self._emit()

    def _unregister_all(self) -> None:
        for action_id, hotkey_id in list(self._active.items()):
            ok, error = self._backend.unregister(hotkey_id)
            if not ok:
                log(
                    f"注销截图热键失败 action={action_id} id={hotkey_id} error={error}"
                )
            self._id_actions.pop(hotkey_id, None)
        self._active.clear()

    # ------------------------------------------------------------ 修改
    def apply(
        self,
        action_id: str,
        modifiers: int,
        vk: int,
        enabled: bool = True,
        replace: bool = False,
    ) -> ApplyResult:
        action = ACTION_BY_ID.get(action_id)
        if action is None:
            return ApplyResult(False, "未知的截图功能")
        modifiers = int(modifiers or 0) & hk.ALL_MODIFIERS
        vk = int(vk or 0)
        current = self._bindings[action_id]

        if not enabled:
            changed = (
                current.enabled
                or action_id in self._active
                or (current.modifiers, current.vk) != (modifiers, vk)
            )
            if changed:
                old_id = self._active.pop(action_id, None)
                if old_id is not None:
                    ok, error = self._backend.unregister(old_id)
                    self._id_actions.pop(old_id, None)
                    if not ok:
                        self._active[action_id] = old_id
                        self._id_actions[old_id] = action_id
                        log(
                            f"注销截图热键失败 action={action_id} id={old_id} error={error}"
                        )
                        return ApplyResult(
                            False, "无法注销旧快捷键，请稍后重试", error
                        )
                current.enabled = False
                current.modifiers = modifiers
                current.vk = vk
                self._states[action_id] = BindingState(
                    action_id, current, STATUS_DISABLED
                )
                self._emit()
            return ApplyResult(True)

        error = validate_binding(modifiers, vk)
        if error:
            return ApplyResult(False, error)

        if (
            current.enabled
            and current.modifiers == modifiers
            and current.vk == vk
            and action_id in self._active
        ):
            return ApplyResult(True)

        conflict = self.find_conflict(action_id, modifiers, vk)
        if conflict and not replace:
            return ApplyResult(
                False,
                f"该快捷键已用于「{ACTION_BY_ID[conflict].label}」",
                conflict_action=conflict,
            )

        if conflict:
            return self._replace(action_id, conflict, modifiers, vk)

        return self._commit(action_id, modifiers, vk)

    def _commit(self, action_id: str, modifiers: int, vk: int) -> ApplyResult:
        had_old = action_id in self._active
        result = self._register(
            HotkeyBinding(action_id, modifiers, vk, True)
        )
        if not result.ok:
            message = self._external_message(result.error)
            self._states[action_id] = BindingState(
                action_id,
                self._bindings[action_id],
                STATUS_ACTIVE if had_old else STATUS_FAILED,
                message,
                result.error,
            )
            self._emit()
            log(
                f"注册截图热键失败 action={action_id} "
                f"key={hk.format_hotkey(modifiers, vk)} error={result.error}"
            )
            return ApplyResult(False, message, result.error, external=True)

        old_id = self._active.pop(action_id, None)
        if old_id is not None:
            self._id_actions.pop(old_id, None)
            ok, error = self._backend.unregister(old_id)
            if not ok:
                log(
                    f"注销旧截图热键失败 action={action_id} id={old_id} error={error}"
                )

        binding = self._bindings[action_id]
        binding.modifiers = modifiers
        binding.vk = vk
        binding.enabled = True
        self._active[action_id] = result.hotkey_id
        self._id_actions[result.hotkey_id] = action_id
        self._states[action_id] = BindingState(
            action_id, binding, STATUS_ACTIVE
        )
        self._emit()
        return ApplyResult(True)

    def _replace(
        self, action_id: str, conflict_id: str, modifiers: int, vk: int
    ) -> ApplyResult:
        had_old = action_id in self._active
        other = self._bindings[conflict_id]
        saved = other.clone()
        other_id = self._active.pop(conflict_id, None)
        if other_id is not None:
            self._id_actions.pop(other_id, None)
            ok, error = self._backend.unregister(other_id)
            if not ok:
                self._active[conflict_id] = other_id
                self._id_actions[other_id] = conflict_id
                log(
                    f"解除冲突热键失败 action={conflict_id} id={other_id} error={error}"
                )
                return ApplyResult(
                    False, "无法解除原功能的快捷键，请稍后重试", error
                )

        result = self._register(HotkeyBinding(action_id, modifiers, vk, True))
        if not result.ok:
            # 回滚：把被替换的功能按原样重新注册
            rollback = self._register(saved)
            if rollback.ok:
                self._active[conflict_id] = rollback.hotkey_id
                self._id_actions[rollback.hotkey_id] = conflict_id
                self._states[conflict_id] = BindingState(
                    conflict_id, saved, STATUS_ACTIVE
                )
            else:
                log(
                    f"回滚热键失败 action={conflict_id} "
                    f"key={saved.text} error={rollback.error}"
                )
                self._states[conflict_id] = BindingState(
                    conflict_id,
                    saved,
                    STATUS_FAILED,
                    self._external_message(rollback.error),
                    rollback.error,
                )
            message = self._external_message(result.error)
            self._states[action_id] = BindingState(
                action_id,
                self._bindings[action_id],
                STATUS_ACTIVE if had_old else STATUS_FAILED,
                message,
                result.error,
            )
            self._emit()
            return ApplyResult(False, message, result.error, external=True)

        old_id = self._active.pop(action_id, None)
        if old_id is not None:
            self._id_actions.pop(old_id, None)
            ok, error = self._backend.unregister(old_id)
            if not ok:
                log(
                    f"注销旧截图热键失败 action={action_id} id={old_id} error={error}"
                )

        # 被替换的功能解除绑定（保留原组合用于展示，但不再注册）
        other.enabled = False
        self._states[conflict_id] = BindingState(
            conflict_id, other, STATUS_DISABLED
        )

        binding = self._bindings[action_id]
        binding.modifiers = modifiers
        binding.vk = vk
        binding.enabled = True
        self._active[action_id] = result.hotkey_id
        self._id_actions[result.hotkey_id] = action_id
        self._states[action_id] = BindingState(
            action_id, binding, STATUS_ACTIVE
        )
        self._emit()
        return ApplyResult(True)

    def enable(self, action_id: str) -> ApplyResult:
        binding = self._bindings[action_id]
        if not binding.configured:
            return ApplyResult(False, "请先录制一个快捷键")
        return self.apply(
            action_id, binding.modifiers, binding.vk, enabled=True
        )

    def disable(self, action_id: str) -> ApplyResult:
        binding = self._bindings[action_id]
        return self.apply(
            action_id, binding.modifiers, binding.vk, enabled=False
        )

    def reset(self, action_id: str) -> ApplyResult:
        default = default_binding(action_id)
        if not default.enabled:
            return self.apply(action_id, 0, 0, enabled=False)
        return self.apply(
            action_id, default.modifiers, default.vk, enabled=True
        )

    def retry(self, action_id: str) -> ApplyResult:
        binding = self._bindings[action_id]
        if not binding.enabled:
            return ApplyResult(False, "该快捷键未启用")
        if not binding.configured:
            return ApplyResult(False, "请先录制一个快捷键")
        if action_id in self._active:
            return ApplyResult(True)
        return self._commit(action_id, binding.modifiers, binding.vk)

    # ------------------------------------------------------------ 内部
    def _register(self, binding: HotkeyBinding) -> RegisterResult:
        try:
            return self._backend.register(
                binding.modifiers | hk.MOD_NOREPEAT, binding.vk
            )
        except Exception as exc:  # noqa: BLE001
            log(
                f"注册截图热键异常 action={binding.action} "
                f"key={binding.text} error={exc}"
            )
            return RegisterResult(False, 0, -1)

    def _external_message(self, error: int) -> str:
        if error == ERROR_HOTKEY_ALREADY_REGISTERED:
            return "该快捷键可能已被系统或其他程序占用，请更换（错误码 1409）"
        if error:
            return f"该快捷键可能已被系统或其他程序占用，请更换（错误码 {error}）"
        return "该快捷键可能已被系统或其他程序占用，请更换"

    def _emit(self) -> None:
        if self._on_change is not None:
            try:
                self._on_change()
            except Exception:
                pass
