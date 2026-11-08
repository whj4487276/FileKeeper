"""开发期图标生成器（需要 Pillow）。

运行：python tools/make_icons.py
产物：assets/icons/*.png、assets/app.ico
运行时只用 tkinter 的 PhotoImage 读取 PNG，不依赖 Pillow。
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

BASE = Path(__file__).resolve().parent.parent
ICON_DIR = BASE / "assets" / "icons"
ICON_DIR.mkdir(parents=True, exist_ok=True)

GRID = 24
K = 4
PX = GRID * K
LW = 1.9

DIM = (152, 162, 180, 255)
ACC = (76, 141, 255, 255)
WHITE = (244, 247, 255, 255)


def _p(*vals):
    return [v * K for v in vals]


def _w(width):
    return max(1, int(round(width * K)))


def new():
    img = Image.new("RGBA", (PX, PX), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


def line(d, x1, y1, x2, y2, color, w=LW):
    d.line(_p(x1, y1, x2, y2), fill=color, width=_w(w), joint="curve")


def poly(d, pts, color, w=LW, close=False):
    flat = []
    for x, y in pts:
        flat.extend(_p(x, y))
    if close:
        flat.extend(_p(*pts[0]))
    d.line(flat, fill=color, width=_w(w), joint="curve")


def circle(d, cx, cy, r, color, w=LW, fill=None):
    d.ellipse(_p(cx - r, cy - r, cx + r, cy + r), outline=color, width=_w(w), fill=fill)


def rrect(d, x1, y1, x2, y2, r, color, w=LW, fill=None):
    d.rounded_rectangle(
        _p(x1, y1, x2, y2), radius=r * K, outline=color, width=_w(w), fill=fill
    )


def ico_home(color):
    img, d = new()
    poly(d, [(3.0, 10.9), (12.0, 3.3), (21.0, 10.9)], color)
    poly(d, [(5.4, 10.4), (5.4, 20.4), (18.6, 20.4), (18.6, 10.4)], color)
    poly(d, [(10.1, 20.4), (10.1, 14.0), (13.9, 14.0), (13.9, 20.4)], color, 1.7)
    return img


def ico_tasks(color):
    img, d = new()
    for y in (6.6, 12.0, 17.4):
        circle(d, 5.0, y, 1.6, color, 1.7)
        line(d, 9.2, y, 20.4, y, color, 1.7)
    return img


def ico_files(color):
    img, d = new()
    poly(
        d,
        [(3.2, 6.4), (9.3, 6.4), (11.3, 9.1), (20.8, 9.1), (20.8, 19.6), (3.2, 19.6)],
        color,
        close=True,
    )
    line(d, 3.6, 12.4, 20.4, 12.4, color, 1.5)
    return img


def ico_history(color):
    img, d = new()
    circle(d, 12.0, 12.2, 8.3, color)
    line(d, 12.0, 12.2, 12.0, 7.4, color, 1.8)
    line(d, 12.0, 12.2, 15.7, 14.1, color, 1.8)
    return img


def ico_settings(color):
    img, d = new()
    for y, kx in ((6.8, 9.6), (12.0, 15.0), (17.2, 7.8)):
        line(d, 3.4, y, 20.6, y, color, 1.5)
        d.ellipse(_p(kx - 2.5, y - 2.5, kx + 2.5, y + 2.5), fill=color)
    return img


def ico_power(color):
    """电源符号：顶部开口的圆 + 竖线。"""
    img, d = new()
    d.arc(
        _p(4.0, 5.0, 20.0, 21.0),
        start=300,
        end=240,
        fill=color,
        width=_w(1.9),
    )
    line(d, 12.0, 3.4, 12.0, 11.6, color, 2.1)
    return img


def ico_alarm(color):
    """闹钟：圆 + 指针 + 两侧铃线。"""
    img, d = new()
    circle(d, 12.0, 13.4, 7.2, color)
    line(d, 12.0, 13.4, 12.0, 9.3, color, 1.8)
    line(d, 12.0, 13.4, 15.0, 15.0, color, 1.8)
    line(d, 7.4, 7.2, 5.2, 5.0, color, 1.7)
    line(d, 16.6, 7.2, 18.8, 5.0, color, 1.7)
    return img


def ico_timer(color):
    """秒表：圆 + 顶部按钮 + 指针。"""
    img, d = new()
    circle(d, 12.0, 14.0, 7.0, color)
    line(d, 9.6, 3.4, 14.4, 3.4, color, 2.0)
    line(d, 12.0, 3.6, 12.0, 6.6, color, 1.8)
    line(d, 12.0, 14.0, 12.0, 9.8, color, 1.8)
    line(d, 12.0, 14.0, 14.8, 15.6, color, 1.8)
    return img


def ico_camera(color):
    """相机：机身 + 镜头 + 取景凸起。"""
    img, d = new()
    rrect(d, 3.2, 7.6, 20.8, 19.8, 2.4, color, 1.8)
    rrect(d, 8.6, 4.4, 15.4, 7.8, 1.4, color, 1.8)
    circle(d, 12.0, 13.6, 3.8, color, 1.8)
    circle(d, 12.0, 13.6, 1.2, color, 1.4, fill=color)
    return img


def make_logo(size: int = 64) -> Image.Image:
    top = (92, 156, 255)
    bot = (48, 100, 224)
    grad = Image.new("RGBA", (size, size))
    gd = ImageDraw.Draw(grad)
    for y in range(size):
        t = y / max(1, size - 1)
        col = tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)) + (255,)
        gd.line([(0, y), (size, y)], fill=col)

    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, size - 1, size - 1], radius=int(size * 0.27), fill=255
    )
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    img.paste(grad, (0, 0), mask)

    s = size / 24.0
    d = ImageDraw.Draw(img)

    def P(*vals):
        return [v * s for v in vals]

    w = max(1, int(round(1.7 * s)))
    body = [(5.2, 8.6), (10.2, 8.6), (11.8, 10.8), (18.8, 10.8), (18.8, 17.6), (5.2, 17.6)]
    flat = []
    for x, y in body:
        flat.extend(P(x, y))
    flat.extend(P(*body[0]))
    d.line(flat, fill=WHITE, width=w, joint="curve")

    d.line(P(9.6, 14.4) + P(11.4, 16.2), fill=WHITE, width=w, joint="curve")
    d.line(P(11.4, 16.2) + P(15.2, 12.4), fill=WHITE, width=w, joint="curve")
    return img


def main() -> None:
    icons = {
        "home": ico_home,
        "tasks": ico_tasks,
        "files": ico_files,
        "history": ico_history,
        "settings": ico_settings,
        "power": ico_power,
        "alarm": ico_alarm,
        "timer": ico_timer,
        "camera": ico_camera,
    }
    for name, fn in icons.items():
        for suffix, color in (("", DIM), ("_active", ACC), ("_white", WHITE)):
            base = fn(color)
            for size in (24, 36, 48):
                image = base.resize((size, size), Image.LANCZOS)
                filename = f"{name}{suffix}.png" if size == 24 else f"{name}{suffix}_{size}.png"
                image.save(ICON_DIR / filename)

    for size in (40, 60, 80):
        make_logo(size).save(ICON_DIR / (f"logo_{size}.png" if size != 40 else "logo.png"))
    make_logo(96).save(ICON_DIR / "logo_96.png")

    sizes = [16, 24, 32, 48, 64, 128, 256]
    big = make_logo(256)
    big.save(BASE / "assets" / "app.ico", format="ICO", sizes=[(s, s) for s in sizes])
    print(f"icons -> {ICON_DIR}")
    print(f"icon  -> {BASE / 'assets' / 'app.ico'}")


if __name__ == "__main__":
    main()
