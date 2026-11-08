"""时间提醒：倒计时 / 指定时间，到点响铃并弹窗。

支持重复：
- 倒计时：循环 N 次，或一直重复到手动停止
- 指定时间：每天 / 每个整点 / 每小时的第 X 分 Y 秒，并可限定只在某个时间段内提醒

提醒方式由用户选择：
- 「滴」两声（间隔约 0.12 秒）
- 弹窗确认提醒
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from datetime import time as clock_time

from .fsutil import ISO_FMT, now_iso, parse_iso

SOURCE_LABELS = {
    "countdown": "倒计时",
    "clock": "指定时间",
}

REPEAT_LABELS = {
    "none": "不重复",
    "count": "循环指定次数",
    "forever": "一直重复",
    "daily": "每天",
    "hourly": "每个整点",
    "hour_min": "每小时固定时刻",
}


# ---------------------------------------------------------------- 计划
def make_alarm(
    target: datetime,
    kind: str,
    sound: bool = True,
    dialog: bool = True,
    label: str = "",
    text: str = "",
    repeat: str = "none",
    repeat_total: int = 1,
    interval_seconds: int = 0,
    minute: int = 0,
    second: int = 0,
    window_enabled: bool = False,
    window_start: str = "09:00",
    window_end: str = "18:00",
) -> dict:
    return {
        "target": target.strftime(ISO_FMT),
        "created": now_iso(),
        "kind": kind,
        "sound": bool(sound),
        "dialog": bool(dialog),
        "label": str(label or "")[:80],
        "text": str(text or "")[:200],
        "repeat": repeat if repeat in REPEAT_LABELS else "none",
        "repeat_total": max(1, int(repeat_total or 1)),
        "interval_seconds": max(1, int(interval_seconds or 1)),
        "minute": max(0, min(59, int(minute or 0))),
        "second": max(0, min(59, int(second or 0))),
        "window_enabled": bool(window_enabled),
        "window_start": str(window_start or "09:00"),
        "window_end": str(window_end or "18:00"),
        "fired": 0,
    }


def alarm_target(alarm: dict | None) -> datetime | None:
    if not alarm:
        return None
    return parse_iso(str(alarm.get("target", "")))


def is_active(alarm: dict | None, now: datetime | None = None) -> bool:
    target = alarm_target(alarm)
    if target is None:
        return False
    return target > (now or datetime.now())


def seconds_left(target: datetime, now: datetime | None = None) -> int:
    return max(0, int((target - (now or datetime.now())).total_seconds()))


def human_hms(seconds: int) -> str:
    """把秒数显示成 00:09:59（超过一天带「天」）。"""
    seconds = max(0, int(seconds))
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    text = f"{hours:02d}:{minutes:02d}:{secs:02d}"
    if days:
        return f"{days} 天 {text}"
    return text


def human_target(target: datetime) -> str:
    delta = (target.date() - datetime.now().date()).days
    prefix = {0: "今天", 1: "明天", 2: "后天"}.get(delta)
    if prefix:
        return f"{prefix} {target.strftime('%H:%M:%S')}"
    return target.strftime("%Y-%m-%d %H:%M:%S")


def parse_datetime(date_text: str, time_text: str) -> datetime | None:
    try:
        date_part = datetime.strptime(date_text.strip(), "%Y-%m-%d").date()
        parts = [int(x) for x in str(time_text).strip().split(":")]
    except (ValueError, TypeError):
        return None
    if len(parts) == 2:
        parts.append(0)
    if len(parts) != 3:
        return None
    hour, minute, second = parts
    if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
        return None
    return datetime(date_part.year, date_part.month, date_part.day, hour, minute, second)


# ---------------------------------------------------------------- 重复
def parse_hhmm(text: str, default: tuple[int, int] = (0, 0)) -> tuple[int, int]:
    try:
        hour, minute = (int(x) for x in str(text).strip().split(":"))
    except (ValueError, TypeError):
        return default
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return default
    return hour, minute


def in_window(moment: datetime, start: tuple[int, int], end: tuple[int, int]) -> bool:
    """moment 的时刻是否落在 [start, end] 内（支持跨零点的窗口）。"""
    current = moment.time()
    begin = clock_time(start[0], start[1])
    finish = clock_time(end[0], end[1])
    if begin <= finish:
        return begin <= current <= finish
    return current >= begin or current <= finish


def advance_into_window(
    moment: datetime, start: tuple[int, int], end: tuple[int, int]
) -> datetime:
    """把时间往后推到下一个窗口起点。"""
    if in_window(moment, start, end):
        return moment
    for offset in range(0, 3):
        day = moment + timedelta(days=offset)
        candidate = day.replace(hour=start[0], minute=start[1], second=0, microsecond=0)
        if candidate > moment:
            return candidate
    return moment + timedelta(days=1)


def next_target(alarm: dict | None, now: datetime | None = None) -> datetime | None:
    """本次提醒结束后，下一次应该在什么时候响；不重复则返回 None。"""
    if not alarm:
        return None
    current = now or datetime.now()
    repeat = str(alarm.get("repeat", "none"))

    if repeat in ("count", "forever"):
        interval = max(1, int(alarm.get("interval_seconds", 60) or 60))
        if repeat == "count":
            total = max(1, int(alarm.get("repeat_total", 1) or 1))
            # 本次已经响过一次，所以「已响次数 + 1」用完后就不再排下一轮
            if int(alarm.get("fired", 0) or 0) + 1 >= total:
                return None
        return current + timedelta(seconds=interval)

    if repeat == "daily":
        base = alarm_target(alarm) or current
        candidate = current.replace(
            hour=base.hour, minute=base.minute, second=base.second, microsecond=0
        )
        if candidate <= current:
            candidate += timedelta(days=1)
        return candidate

    if repeat in ("hourly", "hour_min"):
        if repeat == "hourly":
            candidate = (current + timedelta(hours=1)).replace(
                minute=0, second=0, microsecond=0
            )
        else:
            minute = max(0, min(59, int(alarm.get("minute", 0) or 0)))
            second = max(0, min(59, int(alarm.get("second", 0) or 0)))
            candidate = current.replace(minute=minute, second=second, microsecond=0)
            if candidate <= current:
                candidate += timedelta(hours=1)
        if alarm.get("window_enabled"):
            start = parse_hhmm(str(alarm.get("window_start", "09:00")), (9, 0))
            end = parse_hhmm(str(alarm.get("window_end", "18:00")), (18, 0))
            candidate = advance_into_window(candidate, start, end)
        return candidate

    return None


def advance(alarm: dict | None, now: datetime | None = None) -> dict | None:
    """响过之后推进到下一次；不重复或次数用完则返回 None。"""
    if not alarm:
        return None
    nxt = next_target(alarm, now)
    if nxt is None:
        return None
    updated = dict(alarm)
    updated["fired"] = int(alarm.get("fired", 0) or 0) + 1
    updated["target"] = nxt.strftime(ISO_FMT)
    return updated


def repeat_label(alarm: dict | None) -> str:
    """给状态卡用的重复描述。"""
    if not alarm:
        return ""
    repeat = str(alarm.get("repeat", "none"))
    if repeat == "count":
        total = max(1, int(alarm.get("repeat_total", 1) or 1))
        fired = int(alarm.get("fired", 0) or 0)
        return f"第 {min(fired + 1, total)}/{total} 次"
    if repeat == "forever":
        fired = int(alarm.get("fired", 0) or 0)
        return f"第 {fired + 1} 次（一直重复）"
    if repeat == "daily":
        return "每天重复"
    if repeat == "hourly":
        text = "每个整点"
    elif repeat == "hour_min":
        text = f"每小时 {int(alarm.get('minute', 0)):02d}:{int(alarm.get('second', 0)):02d}"
    else:
        return ""
    if alarm.get("window_enabled"):
        text += f"（{alarm.get('window_start')}–{alarm.get('window_end')}）"
    return text


# ---------------------------------------------------------------- 声音
_BEEP_BYTES: bytes | None = None


def _build_beep(
    frequency: float = 880.0,
    duration_ms: int = 160,
    sample_rate: int = 22050,
    volume: float = 0.6,
) -> bytes:
    """合成一段短「滴」声的 WAV 数据（不依赖系统声音方案）。"""
    import io
    import math
    import struct
    import wave

    frames = int(sample_rate * duration_ms / 1000)
    fade_in = max(1, int(sample_rate * 0.008))
    fade_out = max(1, int(sample_rate * 0.025))
    payload = bytearray()
    for i in range(frames):
        envelope = min(
            1.0,
            i / fade_in if fade_in else 1.0,
            (frames - i) / fade_out if fade_out else 1.0,
        )
        sample = math.sin(2.0 * math.pi * frequency * (i / sample_rate))
        payload += struct.pack("<h", int(32767 * volume * envelope * sample))

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(bytes(payload))
    return buffer.getvalue()


def _play_once(winsound, data: bytes) -> bool:
    """winsound.PlaySound 失败时才抛异常，成功返回 None。"""
    try:
        winsound.PlaySound(data, winsound.SND_MEMORY | winsound.SND_NODEFAULT)
        return True
    except Exception:
        return False


def _beep_worker() -> None:
    global _BEEP_BYTES
    try:
        import winsound
    except Exception:
        return

    if _BEEP_BYTES is None:
        try:
            _BEEP_BYTES = _build_beep()
        except Exception:
            _BEEP_BYTES = b""

    played = False
    for index in range(2):
        if _BEEP_BYTES and _play_once(winsound, _BEEP_BYTES):
            played = True
        else:
            # 声卡不可用时退回主板蜂鸣器
            try:
                winsound.Beep(880, 160)
                played = True
            except Exception:
                break
        if index == 0:
            time.sleep(0.13)

    if not played:
        try:
            winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS | winsound.SND_ASYNC)
        except Exception:
            try:
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            except Exception:
                pass


def _ensure_beep() -> bytes:
    global _BEEP_BYTES
    if _BEEP_BYTES is None:
        try:
            _BEEP_BYTES = _build_beep()
        except Exception:
            _BEEP_BYTES = b""
    return _BEEP_BYTES


def play_beep_once() -> None:
    """单独一声「滴」（循环报警时由调用方在自己的线程里反复调用）。"""
    try:
        import winsound
    except Exception:
        return
    data = _ensure_beep()
    if data and _play_once(winsound, data):
        return
    try:
        winsound.Beep(880, 160)
    except Exception:
        pass


def play_double_beep() -> None:
    """在后台线程里「滴」两声，避免卡住界面。"""
    threading.Thread(target=_beep_worker, daemon=True).start()
