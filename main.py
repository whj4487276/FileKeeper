"""电脑百宝箱启动入口。"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))


def enable_dpi_awareness() -> None:
    """让界面在高分屏下保持清晰（必须在创建窗口前调用）。"""
    try:
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def write_crash_log(exc_info) -> None:
    try:
        from datetime import datetime

        from fk.paths import log_file

        with open(log_file(), "a", encoding="utf-8") as handle:
            handle.write(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}]\n")
            handle.write("".join(traceback.format_exception(*exc_info)))
    except Exception:
        pass


def show_fatal(message: str) -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("电脑百宝箱启动失败", message)
        root.destroy()
    except Exception:
        pass


def main() -> None:
    enable_dpi_awareness()

    from fk.paths import APP_TAGLINE, APP_TITLE
    from fk.single import SingleInstance, activate_existing

    guard = SingleInstance()
    if guard.already_running:
        # 已经有副本在跑：只把它叫出来，然后安静退出
        activate_existing(f"{APP_TITLE} · {APP_TAGLINE}")
        return

    from fk.config import Config
    from fk.paths import config_file
    from fk.ui.app import App

    start_minimized = "--minimized" in sys.argv[1:]
    config = Config.load(config_file())
    app = App(config, start_minimized=start_minimized)
    try:
        app.mainloop()
    finally:
        guard.release()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        info = sys.exc_info()
        write_crash_log(info)
        text = "".join(traceback.format_exception(*info))
        show_fatal(text[-2500:])
        sys.exit(1)
