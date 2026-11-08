"""电脑百宝箱 安装程序（打包成单个 exe）。

图形界面安装，或使用命令行静默安装:

    FileKeeper-Setup.exe --dir "D:\\Apps\\FileKeeper" --no-shortcuts --no-launch
"""
from __future__ import annotations

import base64
import os
import shutil
import subprocess
import sys
import threading
import traceback
import winreg
from pathlib import Path

APP_NAME = "电脑百宝箱"
APP_VERSION = "2.2.1"
EXE_NAME = "电脑百宝箱.exe"
UNINSTALL_NAME = "uninstall.bat"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\FileKeeper"

BG = "#101218"
CARD = "#171B23"
BORDER = "#2A3140"
TEXT = "#E8EBF2"
DIM = "#9AA5B8"
MUTED = "#6B7488"
ACCENT = "#4C8DFF"
ACCENT_HOVER = "#6BA3FF"
GREEN = "#3ECF8E"
RED = "#F26B76"


# ---------------------------------------------------------------- 路径
def resource_dir() -> Path:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base)
    here = Path(__file__).resolve().parent
    if (here / "assets").exists():
        return here
    parent = here.parent
    if (parent / "assets").exists():
        return parent
    return here


def payload_dir() -> Path:
    return resource_dir() / "payload"


def previous_target() -> Path | None:
    """上一次安装的位置（用于升级时默认覆盖旧目录）。"""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as key:
            value, _ = winreg.QueryValueEx(key, "InstallLocation")
        text = str(value or "").strip()
        if text:
            return Path(text)
    except Exception:
        pass
    return None


def default_target() -> Path:
    previous = previous_target()
    if previous is not None:
        return previous
    root = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(root) / "电脑百宝箱"


# ---------------------------------------------------------------- 快捷方式
_SHORTCUT_PS = r"""
$ErrorActionPreference = 'Stop'
$target = $env:FK_TARGET
$shell = New-Object -ComObject WScript.Shell
$dirs = @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))
$legacy = @('文件管家.lnk')
foreach ($dir in $dirs) {
    if (-not $dir) { continue }
    foreach ($name in $legacy) {
        $old = Join-Path $dir $name
        if (Test-Path $old) { Remove-Item $old -Force -ErrorAction SilentlyContinue }
    }
    $path = Join-Path $dir '电脑百宝箱.lnk'
    $link = $shell.CreateShortcut($path)
    $link.TargetPath = $target
    $link.WorkingDirectory = Split-Path $target
    $link.IconLocation = "$target,0"
    $link.Description = '电脑百宝箱 - 备份 / 定时关机 / 时间闹钟 / 计时器 / 截图'
    $link.Save()
}
"""


def create_shortcuts(exe_path: Path) -> bool:
    script = base64.b64encode(_SHORTCUT_PS.encode("utf-16-le")).decode("ascii")
    env = dict(os.environ)
    env["FK_TARGET"] = str(exe_path)
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-EncodedCommand",
                script,
            ],
            env=env,
            capture_output=True,
            timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return result.returncode == 0
    except Exception:
        return False


def remove_shortcuts() -> None:
    for folder in ("Desktop", "Programs"):
        pass


# ---------------------------------------------------------------- 注册表
_LAST_REG_ERROR = ""


def register_uninstall(target: Path) -> bool:
    global _LAST_REG_ERROR
    try:
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, UNINSTALL_KEY, 0, winreg.KEY_WRITE
        ) as key:
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, f"{APP_NAME} {APP_VERSION}")
            winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, APP_VERSION)
            winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, "FileKeeper")
            winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, str(target))
            winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, str(target / EXE_NAME))
            winreg.SetValueEx(
                key, "UninstallString", 0, winreg.REG_SZ, str(target / UNINSTALL_NAME)
            )
            winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)
        _LAST_REG_ERROR = ""
        return True
    except Exception as exc:  # noqa: BLE001
        _LAST_REG_ERROR = repr(exc)
        return False


# ---------------------------------------------------------------- 安装
def kill_running() -> None:
    try:
        subprocess.run(
            ["taskkill", "/IM", EXE_NAME, "/F"],
            capture_output=True,
            timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        pass


def perform_install(target: Path, shortcuts: bool = True, log=print) -> Path:
    payload = payload_dir()
    source = payload / EXE_NAME
    if not source.exists():
        raise FileNotFoundError(f"安装包内缺少 {EXE_NAME}")

    log("正在结束已运行的实例…")
    kill_running()

    log(f"正在创建目录 {target}")
    target.mkdir(parents=True, exist_ok=True)

    log("正在复制程序文件…")
    dest = target / EXE_NAME
    shutil.copy2(source, dest)

    payload_uninstall = payload / UNINSTALL_NAME
    if payload_uninstall.exists():
        shutil.copy2(payload_uninstall, target / UNINSTALL_NAME)

    if shortcuts:
        log("正在创建桌面和开始菜单快捷方式…")
        create_shortcuts(dest)

    log("正在写入卸载信息…")
    if not register_uninstall(target):
        log(f"（提示）未能写入卸载信息：{_LAST_REG_ERROR}")

    log("安装完成")
    return dest


# ---------------------------------------------------------------- 图形界面
def run_gui() -> int:
    import tkinter as tk
    from tkinter import filedialog, messagebox

    root = tk.Tk()
    root.title(f"{APP_NAME} 安装程序")
    root.configure(bg=BG)
    width, height = 620, 470
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    root.geometry(f"{width}x{height}+{(screen_w - width) // 2}+{(screen_h - height) // 3}")
    root.resizable(False, False)

    icon = resource_dir() / "assets" / "app.ico"
    try:
        if icon.exists():
            root.iconbitmap(default=str(icon))
    except Exception:
        pass

    logo_path = resource_dir() / "assets" / "logo_96.png"
    if not logo_path.exists():
        logo_path = resource_dir() / "assets" / "icons" / "logo_96.png"
    logo_image = None
    try:
        if logo_path.exists():
            logo_image = tk.PhotoImage(file=str(logo_path))
    except Exception:
        logo_image = None

    header = tk.Frame(root, bg=BG)
    header.pack(fill="x", padx=28, pady=(26, 8))
    if logo_image is not None:
        label = tk.Label(header, image=logo_image, bg=BG)
        label.image = logo_image
        label.pack(side="left", padx=(0, 16))
    text_box = tk.Frame(header, bg=BG)
    text_box.pack(side="left", fill="x", expand=True)
    tk.Label(
        text_box, text=f"安装 {APP_NAME}", bg=BG, fg=TEXT, font=("Microsoft YaHei UI", 18, "bold")
    ).pack(anchor="w")
    tk.Label(
        text_box,
        text=f"版本 {APP_VERSION} · 备份 / 关机 / 闹钟 / 计时器 / 截图",
        bg=BG,
        fg=DIM,
        font=("Microsoft YaHei UI", 9),
    ).pack(anchor="w", pady=(4, 0))

    card = tk.Frame(root, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
    card.pack(fill="both", expand=True, padx=28, pady=(10, 0))
    inner = tk.Frame(card, bg=CARD)
    inner.pack(fill="both", expand=True, padx=20, pady=18)

    tk.Label(
        inner, text="安装位置", bg=CARD, fg=DIM, font=("Microsoft YaHei UI", 9)
    ).pack(anchor="w")

    path_row = tk.Frame(inner, bg=CARD)
    path_row.pack(fill="x", pady=(6, 0))

    path_var = tk.StringVar(value=str(default_target()))
    entry_frame = tk.Frame(path_row, bg="#212734", highlightbackground=BORDER, highlightthickness=1)
    entry_frame.pack(side="left", fill="x", expand=True)
    entry = tk.Entry(
        entry_frame,
        textvariable=path_var,
        bg="#212734",
        fg=TEXT,
        insertbackground=TEXT,
        relief="flat",
        bd=0,
        highlightthickness=0,
        font=("Microsoft YaHei UI", 9),
    )
    entry.pack(fill="both", expand=True, padx=9, pady=7)

    def browse() -> None:
        chosen = filedialog.askdirectory(parent=root, title="选择安装位置")
        if chosen:
            path_var.set(str(Path(chosen) / "FileKeeper"))

    tk.Button(
        path_row,
        text="浏览…",
        command=browse,
        bg="#212734",
        fg=TEXT,
        activebackground="#272E3C",
        activeforeground=TEXT,
        relief="flat",
        bd=0,
        highlightthickness=0,
        font=("Microsoft YaHei UI", 9),
        padx=14,
        pady=7,
        cursor="hand2",
    ).pack(side="left", padx=(8, 0))

    shortcut_var = tk.BooleanVar(value=True)
    launch_var = tk.BooleanVar(value=True)
    for text, var in (
        ("创建桌面和开始菜单快捷方式", shortcut_var),
        ("安装完成后立即启动", launch_var),
    ):
        tk.Checkbutton(
            inner,
            text=text,
            variable=var,
            bg=CARD,
            fg=TEXT,
            activebackground=CARD,
            activeforeground=TEXT,
            selectcolor=BG,
            highlightthickness=0,
            bd=0,
            anchor="w",
            font=("Microsoft YaHei UI", 9),
            cursor="hand2",
        ).pack(anchor="w", pady=(10, 0))

    status = tk.Label(
        inner,
        text="点击「开始安装」继续。程序会安装到当前用户目录，不需要管理员权限。",
        bg=CARD,
        fg=MUTED,
        font=("Microsoft YaHei UI", 8),
        justify="left",
        wraplength=500,
    )
    status.pack(anchor="w", pady=(14, 0))

    footer = tk.Frame(root, bg=BG)
    footer.pack(fill="x", padx=28, pady=18)

    install_btn = tk.Button(
        footer,
        text="开始安装",
        bg=ACCENT,
        fg="#FFFFFF",
        activebackground=ACCENT_HOVER,
        activeforeground="#FFFFFF",
        relief="flat",
        bd=0,
        highlightthickness=0,
        font=("Microsoft YaHei UI", 10, "bold"),
        padx=26,
        pady=9,
        cursor="hand2",
    )
    install_btn.pack(side="right")

    close_btn = tk.Button(
        footer,
        text="退出",
        command=root.destroy,
        bg=BG,
        fg=DIM,
        activebackground="#1C212B",
        activeforeground=TEXT,
        relief="flat",
        bd=0,
        highlightthickness=0,
        font=("Microsoft YaHei UI", 10),
        padx=16,
        pady=9,
        cursor="hand2",
    )
    close_btn.pack(side="right", padx=(0, 10))

    state = {"busy": False, "done": False}

    def set_status(text: str, color: str = MUTED) -> None:
        status.configure(text=text, fg=color)

    def worker(target: Path) -> None:
        try:
            perform_install(
                target,
                shortcuts=bool(shortcut_var.get()),
                log=lambda msg: root.after(0, lambda m=msg: set_status(m)),
            )
            root.after(0, lambda: finish(target))
        except Exception as exc:  # noqa: BLE001
            message = f"安装失败：{exc}"
            root.after(0, lambda: fail(message))

    def finish(target: Path) -> None:
        state["busy"] = False
        state["done"] = True
        set_status(f"安装完成。程序位置：{target}", GREEN)
        install_btn.configure(text="完成", bg=GREEN, state="normal", command=root.destroy)
        if launch_var.get():
            try:
                subprocess.Popen(
                    [str(target / EXE_NAME)],
                    cwd=str(target),
                    close_fds=True,
                )
                root.after(1200, root.destroy)
            except Exception:
                pass

    def fail(message: str) -> None:
        state["busy"] = False
        set_status(message, RED)
        install_btn.configure(state="normal", text="重试")
        messagebox.showerror("安装失败", message, parent=root)

    def start() -> None:
        if state["busy"]:
            return
        target_text = path_var.get().strip()
        if not target_text:
            messagebox.showwarning("请填写路径", "请选择安装位置。", parent=root)
            return
        target = Path(target_text)
        state["busy"] = True
        install_btn.configure(state="disabled", text="正在安装…")
        set_status("准备安装…")
        threading.Thread(target=worker, args=(target,), daemon=True).start()

    install_btn.configure(command=start)
    root.mainloop()
    return 0


# ---------------------------------------------------------------- 命令行
def run_cli(argv: list[str]) -> int:
    def arg_value(flag: str) -> str | None:
        if flag in argv:
            index = argv.index(flag)
            if index + 1 < len(argv):
                return argv[index + 1]
        return None

    target = Path(arg_value("--dir") or default_target())
    shortcuts = "--no-shortcuts" not in argv
    launch = "--no-launch" not in argv

    lines: list[str] = []

    def log(message: str) -> None:
        lines.append(message)

    try:
        dest = perform_install(target, shortcuts=shortcuts, log=log)
        log(f"OK {dest}")
        code = 0
    except Exception:
        log("FAILED")
        log(traceback.format_exc())
        code = 1

    try:
        target.mkdir(parents=True, exist_ok=True)
        (target / "install_log.txt").write_text("\n".join(lines), encoding="utf-8")
    except OSError:
        pass

    if code == 0 and launch:
        try:
            subprocess.Popen([str(target / EXE_NAME)], cwd=str(target), close_fds=True)
        except Exception:
            pass
    return code


def main() -> int:
    argv = sys.argv[1:]
    if "--dir" in argv or "--quiet" in argv or "--no-launch" in argv:
        return run_cli(argv)
    return run_gui()


if __name__ == "__main__":
    sys.exit(main())
