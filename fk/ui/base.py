"""页面基类。"""
from __future__ import annotations

import tkinter as tk

from ..theme import C


class Page(tk.Frame):
    title = ""
    subtitle = ""

    def __init__(self, master, app):
        super().__init__(master, bg=C.BG, bd=0, highlightthickness=0)
        self.app = app
        self.cfg = app.config
        self._build()

    # 子类实现
    def _build(self) -> None:  # pragma: no cover - 界面构造
        pass

    def refresh(self) -> None:
        pass

    def on_show(self) -> None:
        self.refresh()

    def on_backup_event(self, kind: str, payload) -> None:
        pass

    # 便捷方法
    def message(self, text: str, kind: str = "info") -> None:
        self.app.status.set_message(text, kind)
