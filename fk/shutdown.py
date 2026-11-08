"""定时关机服务：调用 Windows 自带的 shutdown.exe。

关机由操作系统执行，所以即使本软件退出，计划依然有效（重启计算机会丢失）。
"""
from __future__ import annotations

import ctypes
import subprocess
import sys
from datetime import datetime, timedelta

from .fsutil import ISO_FMT, now_iso, parse_iso

CREATE_NO_WINDOW = 0x08000000
MAX_SECONDS = 31_536_000  # Windows 允许的最大 /t
MIN_LEAD_SECONDS = 20  # 少于这个秒数就直接拒绝，避免来不及反悔

SOURCE_LABELS = {
    "tomorrow8": "第二天 08:00",
    "today8": "当天 08:00",
    "hours10": "10 小时后",
    "custom_time": "自定义时刻",
    "custom_delay": "自定义延时",
}


# ---------------------------------------------------------------- 底层调用
def _run(args: list[str], timeout: int = 20) -> tuple[int, str]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = CREATE_NO_WINDOW
    try:
        proc = subprocess.run(
            ["shutdown"] + args, capture_output=True, timeout=timeout, **kwargs
        )
    except FileNotFoundError:
        return 127, "找不到 shutdown.exe"
    except subprocess.TimeoutExpired:
        return 124, "调用 shutdown 超时"

    out = (proc.stdout or b"").decode("mbcs", "ignore")
    err = (proc.stderr or b"").decode("mbcs", "ignore")
    return proc.returncode, (out + err).strip()


def arm(target: datetime, comment: str = "", replace_existing: bool = False) -> tuple[bool, str]:
    """安排一次定时关机。返回 (是否成功, 错误信息)。

    默认不主动取消系统里已有的关机计划；只有明确要求替换时才先执行
    ``shutdown /a``。这样不会误取消其他程序/用户设置的关机。
    """
    remaining = int((target - datetime.now()).total_seconds())
    if remaining < MIN_LEAD_SECONDS:
        return False, f"距离关机时间太近（不足 {MIN_LEAD_SECONDS} 秒），请重新设定。"
    remaining = min(remaining, MAX_SECONDS)

    if replace_existing:
        _run(["/a"])  # 用户已确认替换本软件自己的旧计划
    args = ["/s", "/t", str(remaining)]
    if comment:
        args += ["/c", comment[:480]]

    code, output = _run(args)
    if code == 0:
        return True, ""
    return False, output or f"shutdown 返回码 {code}"


def cancel() -> tuple[bool, str]:
    """取消关机计划。本来就没有计划也算成功。"""
    code, output = _run(["/a"])
    if code == 0:
        return True, ""
    lowered = output.lower()
    if "1116" in output or "没有" in output or "no shutdown" in lowered:
        return True, ""
    return False, output or f"shutdown 返回码 {code}"


# ---------------------------------------------------------------- 时间计算
def tomorrow_at(hour: int = 8, minute: int = 0, now: datetime | None = None) -> datetime:
    current = now or datetime.now()
    return (current + timedelta(days=1)).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )


def today_at(hour: int = 8, minute: int = 0, now: datetime | None = None) -> tuple[datetime, bool]:
    """今天的 HH:MM；如果已经过去则顺延到明天，第二个返回值表示是否顺延。"""
    current = now or datetime.now()
    target = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= current:
        return target + timedelta(days=1), True
    return target, False


def after_delay(hours: int = 0, minutes: int = 0, now: datetime | None = None) -> datetime:
    current = now or datetime.now()
    return current + timedelta(hours=max(0, hours), minutes=max(0, minutes))


def parse_datetime(text: str, time_text: str) -> datetime | None:
    """把 "2026-10-24" + "08:00" 解析成 datetime。"""
    try:
        date_part = datetime.strptime(text.strip(), "%Y-%m-%d").date()
        hour, minute = (int(x) for x in str(time_text).strip().split(":"))
    except (ValueError, TypeError):
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return datetime(date_part.year, date_part.month, date_part.day, hour, minute)


def seconds_until(target: datetime, now: datetime | None = None) -> int:
    current = now or datetime.now()
    return max(0, int((target - current).total_seconds()))


def human_countdown(seconds: int) -> str:
    seconds = max(0, int(seconds))
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    if days:
        return f"{days} 天 {hours} 小时 {minutes} 分"
    if hours:
        return f"{hours} 小时 {minutes} 分 {secs} 秒"
    if minutes:
        return f"{minutes} 分 {secs} 秒"
    return f"{secs} 秒"


def human_target(target: datetime) -> str:
    today = datetime.now().date()
    delta = (target.date() - today).days
    if delta == 0:
        prefix = "今天"
    elif delta == 1:
        prefix = "明天"
    elif delta == 2:
        prefix = "后天"
    else:
        prefix = target.strftime("%Y-%m-%d")
    return f"{prefix} {target.strftime('%H:%M')}"


# ---------------------------------------------------------------- 计划记录
def boot_marker() -> str:
    """用「开机时刻」区分本次开机，用来判断重启后计划是否还活着。"""
    try:
        uptime_ms = ctypes.windll.kernel32.GetTickCount64()
        boot = datetime.now() - timedelta(milliseconds=uptime_ms)
        return boot.strftime("%Y%m%d%H%M")
    except Exception:
        return ""


def make_plan(target: datetime, source: str) -> dict:
    return {
        "target": target.strftime(ISO_FMT),
        "created": now_iso(),
        "source": source,
        "label": SOURCE_LABELS.get(source, source),
        "boot": boot_marker(),
    }


def plan_target(plan: dict | None) -> datetime | None:
    if not plan:
        return None
    return parse_iso(str(plan.get("target", "")))


def plan_is_alive(plan: dict | None, now: datetime | None = None) -> bool:
    """计划是否仍然有效（同一开机周期内且时间还没到）。"""
    if not plan:
        return False
    target = plan_target(plan)
    if target is None:
        return False
    current = now or datetime.now()
    if target <= current:
        return False
    marker = str(plan.get("boot", ""))
    if marker and boot_marker() and marker != boot_marker():
        return False
    return True
