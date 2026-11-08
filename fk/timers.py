"""多个独立计时器：正计时 / 倒计时。

规则（v1.7）：
- 正计时：从 00:00:00 往上加，默认最大到 99:59:59，超过就回到 00:00:00 继续；
  也可以自定义计数上限，到达上限后立即从最小值重新计数。
- 倒计时：未开始时显示设定的时长，点击开始后倒数，到 00:00:00 结束并弹出提醒。
- 按钮只有两种：开始 / 停止；点「停止」即停止并归零。

状态只在内存里，配置（标题/模式/时长/上限/提醒文字）持久化。
"""
from __future__ import annotations

import time
from dataclasses import dataclass

MAX_TIMERS = 10
MAX_COUNT_SECONDS = 99 * 3600 + 59 * 60 + 59  # 99:59:59

STATUS_IDLE = "idle"
STATUS_RUNNING = "running"
STATUS_FINISHED = "finished"

MODE_UP = "up"
MODE_DOWN = "down"

DEFAULT_DURATION = 300  # 倒计时默认 5 分钟


def format_hms(total_seconds: float | int) -> str:
    seconds = max(0, int(total_seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def parse_hms(hours: int, minutes: int, seconds: int) -> int:
    hours = max(0, min(99, int(hours or 0)))
    minutes = max(0, min(59, int(minutes or 0)))
    seconds = max(0, min(59, int(seconds or 0)))
    return hours * 3600 + minutes * 60 + seconds


def split_hms(total: int) -> tuple[int, int, int]:
    total = max(0, int(total))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return hours, minutes, secs


@dataclass
class Timer:
    index: int
    title: str = ""
    mode: str = MODE_UP
    duration: int = DEFAULT_DURATION
    limit: int = 0  # 正计时上限，0 表示不限（到 99:59:59 回绕）
    reminder: str = ""
    sound: bool = False  # 倒计时结束时是否持续响铃
    status: str = STATUS_IDLE
    _accum: float = 0.0
    _started: float = 0.0

    def __post_init__(self) -> None:
        if not str(self.title or "").strip():
            self.title = f"计时器 {self.index}"
        if self.mode not in (MODE_UP, MODE_DOWN):
            self.mode = MODE_UP
        try:
            duration = int(self.duration or DEFAULT_DURATION)
        except (TypeError, ValueError, OverflowError):
            duration = DEFAULT_DURATION
        try:
            limit = int(self.limit or 0)
        except (TypeError, ValueError, OverflowError):
            limit = 0
        self.duration = max(1, min(duration, MAX_COUNT_SECONDS))
        self.limit = max(0, min(limit, MAX_COUNT_SECONDS))
        self.reminder = str(self.reminder or "")
        self.sound = bool(self.sound)

    # ------------------------------------------------------------ 计算
    def raw_elapsed(self, now: float | None = None) -> float:
        if self.status == STATUS_RUNNING:
            moment = time.monotonic() if now is None else now
            return self._accum + max(0.0, moment - self._started)
        return self._accum

    def _wrap(self, raw: float) -> float:
        """正计时的回绕：到达上限、再超过时就从头再来。"""
        cap = self.limit if self.limit > 0 else MAX_COUNT_SECONDS
        cap = max(1, cap)
        if raw <= cap:
            return raw
        return raw % (cap + 1)

    def initial_seconds(self) -> int:
        """未开始时显示的数字：倒计时是设定时长，正计时是 0。"""
        return self.duration if self.mode == MODE_DOWN else 0

    def display_seconds(self, now: float | None = None) -> float:
        if self.mode == MODE_DOWN:
            return max(0.0, self.duration - self.raw_elapsed(now))
        return self._wrap(self.raw_elapsed(now))

    def display(self, now: float | None = None) -> str:
        if self.status == STATUS_IDLE:
            return format_hms(self.initial_seconds())
        if self.status == STATUS_FINISHED:
            return format_hms(0)
        return format_hms(self.display_seconds(now))

    @property
    def is_active(self) -> bool:
        return self.status == STATUS_RUNNING

    @property
    def button_text(self) -> str:
        return "停止" if self.status == STATUS_RUNNING else "开始"

    # ------------------------------------------------------------ 控制
    def start(self, now: float | None = None) -> None:
        if self.status == STATUS_RUNNING:
            return
        self._accum = 0.0
        self._started = time.monotonic() if now is None else now
        self.status = STATUS_RUNNING

    def stop(self) -> None:
        """停止并归零（回到初始数字）。"""
        self._accum = 0.0
        self._started = 0.0
        self.status = STATUS_IDLE

    reset = stop

    def tick(self, now: float | None = None) -> bool:
        """推进一次；倒计时刚好归零时结束并返回 True。

        结束后立刻回到「未开始」状态，所以显示的仍是设定的初始数字。
        """
        if self.status != STATUS_RUNNING or self.mode != MODE_DOWN:
            return False
        if self.display_seconds(now) > 0:
            return False
        self.stop()
        return True

    # ------------------------------------------------------------ 配置
    def config(self) -> dict:
        return {
            "title": self.title,
            "mode": self.mode,
            "duration": self.duration,
            "limit": self.limit,
            "reminder": self.reminder,
            "sound": self.sound,
        }

    def apply(
        self,
        title: str,
        mode: str,
        duration: int,
        limit: int = 0,
        reminder: str = "",
        sound: bool = False,
    ) -> None:
        self.title = str(title or "").strip() or f"计时器 {self.index}"
        self.mode = mode if mode in (MODE_UP, MODE_DOWN) else MODE_UP
        try:
            duration_value = int(duration or DEFAULT_DURATION)
        except (TypeError, ValueError, OverflowError):
            duration_value = DEFAULT_DURATION
        try:
            limit_value = int(limit or 0)
        except (TypeError, ValueError, OverflowError):
            limit_value = 0
        self.duration = max(1, min(duration_value, MAX_COUNT_SECONDS))
        self.limit = max(0, min(limit_value, MAX_COUNT_SECONDS))
        self.reminder = str(reminder or "")
        self.sound = bool(sound)
        self.stop()

    @classmethod
    def from_config(cls, index: int, data: dict | None) -> "Timer":
        data = data if isinstance(data, dict) else {}
        return cls(
            index=index,
            title=str(data.get("title", "") or ""),
            mode=str(data.get("mode", MODE_UP)),
            duration=data.get("duration", DEFAULT_DURATION) or DEFAULT_DURATION,
            limit=data.get("limit", 0) or 0,
            reminder=str(data.get("reminder", "") or ""),
            sound=bool(data.get("sound", False)),
        )


def load_timers(saved: list | None) -> list[Timer]:
    """从配置还原 10 个计时器（运行状态不保存）。"""
    items = saved if isinstance(saved, list) else []
    timers: list[Timer] = []
    for index in range(1, MAX_TIMERS + 1):
        data = items[index - 1] if index - 1 < len(items) else None
        timers.append(Timer.from_config(index, data if isinstance(data, dict) else None))
    return timers


def dump_timers(timers: list[Timer]) -> list[dict]:
    return [timer.config() for timer in timers]
