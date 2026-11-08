"""用户输入的数字校验。"""
from __future__ import annotations

import re


class InputError(ValueError):
    """输入不是有效整数；调用方应提示并丢弃本次修改。"""


def parse_int(value, label: str, minimum: int | None = None, maximum: int | None = None) -> int:
    text = str(value or "").strip()
    if not text:
        raise InputError(f"「{label}」不能为空，请输入整数。")
    if not re.fullmatch(r"[+-]?\d+", text):
        raise InputError(f"「{label}」需要输入有效整数，例如 1、10、60。")
    try:
        number = int(text)
    except (TypeError, ValueError, OverflowError) as exc:
        raise InputError(f"「{label}」不是有效整数。") from exc
    if minimum is not None and number < minimum:
        raise InputError(f"「{label}」不能小于 {minimum}。")
    if maximum is not None and number > maximum:
        raise InputError(f"「{label}」不能大于 {maximum}。")
    return number
