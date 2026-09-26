"""Generate the raster test images used by the vision benchmark.

Run from the repo root:  uv run python eval/fixtures/assets/make_images.py
Images are committed, so this is only needed to change or rebuild them.
Each image is simple but unambiguous, so a human labeler and a vision model
can agree on what it shows.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).parent


def font(size: int):
    return ImageFont.load_default(size=size)


def image_of_text(name: str, text: str, bg: str, fg: str, size=(640, 200)):
    img = Image.new("RGB", size, bg)
    d = ImageDraw.Draw(img)
    f = font(44)
    box = d.multiline_textbbox((0, 0), text, font=f, align="center")
    w, h = box[2] - box[0], box[3] - box[1]
    d.multiline_text(((size[0] - w) / 2, (size[1] - h) / 2), text, fill=fg, font=f, align="center")
    img.save(OUT / name)


def bar_chart():
    img = Image.new("RGB", (560, 340), "white")
    d = ImageDraw.Draw(img)
    d.text((280, 22), "Sales by region, 2026 (units)", fill="black", font=font(22), anchor="mm")
    d.line((60, 290, 530, 290), fill="black", width=2)
    for i, (label, v) in enumerate([("North", 120), ("South", 80), ("East", 150), ("West", 95)]):
        x = 90 + i * 110
        d.rectangle((x, 290 - v * 1.5, x + 60, 290), fill="#2f6fbd")
        d.text((x + 30, 305), label, fill="black", font=font(18), anchor="mm")
        d.text((x + 30, 290 - v * 1.5 - 14), str(v), fill="black", font=font(18), anchor="mm")
    img.save(OUT / "sales-bars.png")


def line_chart():
    img = Image.new("RGB", (560, 340), "white")
    d = ImageDraw.Draw(img)
    d.text((280, 22), "Monthly website visitors, Jan-Jun 2026", fill="black", font=font(22), anchor="mm")
    d.line((60, 290, 530, 290), fill="black", width=2)
    d.line((60, 60, 60, 290), fill="black", width=2)
    values = [1200, 1500, 1400, 2100, 2600, 3100]
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun"]
    pts = [(90 + i * 85, 290 - v * 0.07) for i, v in enumerate(values)]
    d.line(pts, fill="#c2410c", width=4)
    for (x, y), m, v in zip(pts, months, values):
        d.ellipse((x - 5, y - 5, x + 5, y + 5), fill="#c2410c")
        d.text((x, 305), m, fill="black", font=font(18), anchor="mm")
        d.text((x, y - 16), f"{v:,}", fill="black", font=font(16), anchor="mm")
    img.save(OUT / "visitors-line.png")


def pie_chart():
    img = Image.new("RGB", (560, 320), "white")
    d = ImageDraw.Draw(img)
    d.text((280, 20), "Traffic sources", fill="black", font=font(22), anchor="mm")
    start = -90
    for share, color, label, ly in [(50, "#2f6fbd", "Search 50%", 110), (30, "#c2410c", "Social 30%", 160), (20, "#15803d", "Direct 20%", 210)]:
        end = start + share * 3.6
        d.pieslice((40, 50, 280, 290), start, end, fill=color)
        d.rectangle((320, ly - 10, 340, ly + 10), fill=color)
        d.text((350, ly), label, fill="black", font=font(20), anchor="lm")
        start = end
    img.save(OUT / "pie.png")


def divider():
    img = Image.new("RGB", (600, 24), "white")
    d = ImageDraw.Draw(img)
    for x in range(0, 600, 24):
        d.arc((x, 4, x + 24, 20), 0, 180, fill="#9ca3af", width=2)
    img.save(OUT / "divider.png")


def dark_background():
    """A dark, photo-like backdrop: text over it needs light colors."""
    img = Image.new("RGB", (900, 260), "#101828")
    d = ImageDraw.Draw(img)
    for i in range(0, 900, 6):
        shade = 16 + (i * 40) // 900
        d.line((i, 0, i, 260), fill=(shade, shade + 6, shade + 24))
    d.polygon([(0, 260), (220, 120), (420, 210), (640, 90), (900, 200), (900, 260)], fill="#1f2a44")
    d.ellipse((720, 30, 790, 100), fill="#3b4a6b")
    img.save(OUT / "dark-photo.png")


if __name__ == "__main__":
    image_of_text("sale-banner.png", "SPRING SALE\n30% OFF", "#fde68a", "#7c2d12")
    image_of_text("promo-text.png", "FREE SHIPPING\non orders over $50", "#dbeafe", "#1e3a8a")
    bar_chart()
    line_chart()
    pie_chart()
    divider()
    dark_background()
    print("images written to", OUT)
