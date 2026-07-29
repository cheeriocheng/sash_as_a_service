"""
Prints text vertically down the receipt for a sash, styled after Barbara
Kruger. 
"""

import argparse
import shutil
import sys
import time

from PIL import Image, ImageDraw, ImageFont
from escpos.printer import Usb

# ---- DEFAULT ----
TEXT = "I SHOP THEREFORE I AM"
# -----------------

# Seiko Epson vendor 0x04b8
VENDOR_ID = 0x04B8
# T88V product id 0x0202
PRODUCT_ID = 0x0202

# T88V (80mm paper) prints at 180dpi across a 512-dot-wide head.
# Use 372 instead if printing on 58mm paper.
PAPER_WIDTH_PX = 512
PROFILE = "TM-T88V"
DPI = 180

# Letter height is always maximized to fill the ribbon; the message only
# shrinks below that if it would otherwise print longer than this (cm).
DISPLAY_LENGTH_CM = 65

# Kruger' Oblique Futura Bold. macOS paths first, then common Linux bold
# sans fallbacks (e.g. for the DevTerm), in roughly closest-match order.
FONT_CANDIDATES = [
    ("/System/Library/Fonts/Supplemental/Futura.ttc", 2),  # Futura Bold
    ("/System/Library/Fonts/Supplemental/Arial Bold Italic.ttf", 0),
    ("/System/Library/Fonts/Supplemental/HelveticaNeue.ttc", 0),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0),
    ("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 0),
    ("/usr/share/fonts/truetype/freefont/FreeSansBold.ttf", 0),
]

SHEAR_FACTOR = 0.22  # italic slant amount
FILL_RATIO = 0.92  # glyph height as a fraction of the ribbon width, always maximized to this

PREVIEW_COLUMNS = 48  # terminal columns the ribbon width is squeezed into
PREVIEW_LINE_DELAY = 0.02  # seconds between lines, to feel like it's chugging out


def load_font(size):
    for path, index in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size, index=index)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        # Pillow < 9.2 (e.g. the one bundled with Python 3.7) doesn't accept
        # a size here -- falls back to a small fixed-size bitmap font.
        return ImageFont.load_default()


def measure(font, text):
    tmp = ImageDraw.Draw(Image.new("L", (1, 1)))
    return tmp.multiline_textbbox((0, 0), text, font=font, align="center")


def build_banner_image(text, white_on_black=False):
    text = text.upper()
    bg_fill = 0 if white_on_black else 255
    text_fill = 255 if white_on_black else 0

    # Always maximize letter height first.
    probe_size = 200
    bbox = measure(load_font(probe_size), text)
    scale = (PAPER_WIDTH_PX * FILL_RATIO) / (bbox[3] - bbox[1])
    size = max(1, round(probe_size * scale))
    font = load_font(size)
    bbox = measure(font, text)
    text_w = int(bbox[2] - bbox[0])
    text_h = int(bbox[3] - bbox[1])

    # Shrink size if that made it print longer than DISPLAY_LENGTH_CM
    px_per_cm = DPI / 2.54
    max_w = DISPLAY_LENGTH_CM * px_per_cm
    if text_w > max_w:
        size = max(1, round(size * max_w / text_w))
        font = load_font(size)
        bbox = measure(font, text)
        text_w = int(bbox[2] - bbox[0])
        text_h = int(bbox[3] - bbox[1])

    canvas = Image.new("L", (text_w, PAPER_WIDTH_PX), color=bg_fill)
    draw = ImageDraw.Draw(canvas)
    x = -bbox[0]
    y = (PAPER_WIDTH_PX - text_h) // 2 - bbox[1]
    draw.multiline_text((x, y), text, font=font, fill=text_fill, align="center")

    # Shear for the oblique/italic look.
    w, h = canvas.size
    x_shift = int(round(abs(SHEAR_FACTOR) * h))
    coeffs = (1, SHEAR_FACTOR, -x_shift if SHEAR_FACTOR >= 0 else 0, 0, 1, 0)
    sheared = canvas.transform((w + x_shift, h), Image.AFFINE, coeffs, fillcolor=bg_fill)

    # Rotate so the text reads correctly once the strip is torn off and hangs
    # from the cut edge (the edge nearest the printer at cut time ends up on top.
    return sheared.rotate(90, expand=True, fillcolor=bg_fill)


def print_terminal_preview(image, columns=PREVIEW_COLUMNS, delay=PREVIEW_LINE_DELAY):
    """Simulate the receipt chugging out of the printer, right in the terminal."""
    term_width = shutil.get_terminal_size((columns + 2, 24)).columns
    columns = min(columns, max(10, term_width - 2))

    scale = columns / image.width
    height = max(2, round(image.height * scale))
    height += height % 2  # even, so rows pair up cleanly
    small = image.resize((columns, height), Image.LANCZOS).convert("L")
    pixels = small.load()

    edge = "+" + "-" * columns + "+"
    print(edge)
    for y in range(0, height, 2):
        row = []
        for x in range(columns):
            top = pixels[x, y] < 128
            bottom = pixels[x, y + 1] < 128
            row.append("█" if top and bottom else "▀" if top else "▄" if bottom else " ")
        print("|" + "".join(row) + "|")
        sys.stdout.flush()
        time.sleep(delay)
    print(edge)
    print("✂" + "- " * (columns // 2))
    print(f"Paper length: {image.height / (DPI / 2.54):.1f} cm")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "text", nargs="*", help="Text to print (default: see TEXT variable )"
    )
    style = parser.add_mutually_exclusive_group()
    style.add_argument(
        "--black-on-white",
        action="store_true",
        help="Black text on white paper (default).",
    )
    style.add_argument(
        "--white-on-black",
        action="store_true",
        help="White text on a black bar (Kruger negative).",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Render in the terminal instead of printing -- no printer needed.",
    )
    args = parser.parse_args()

    text = " ".join(args.text) if args.text else TEXT
    image = build_banner_image(text, white_on_black=args.white_on_black)

    if args.preview:
        print_terminal_preview(image)
    else:
        p = Usb(VENDOR_ID, PRODUCT_ID, profile=PROFILE)
        p.image(image)
        # p.cut()
