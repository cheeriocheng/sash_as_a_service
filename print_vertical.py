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
TEXT = "HI"
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

# Separate font list for CJK (Chinese) runs -- the Latin fonts above have no
# glyphs for these codepoints. macOS paths first, then common Linux CJK
# fallbacks (install `fonts-wqy-zenhei` or `fonts-noto-cjk` if none of these
# exist on a given Linux box).
CJK_FONT_CANDIDATES = [
    ("/System/Library/Fonts/PingFang.ttc", 5),  # PingFang SC Medium
    ("/System/Library/Fonts/Hiragino Sans GB.ttc", 2),  # W6 (bold)
    ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 0),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 0),
    ("/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc", 0),
]

# Chinese reads as upright stacked glyphs rather than sideways like the Latin
# runs, so each CJK glyph is pre-rotated to cancel out the whole-canvas
# rotation plus the 180 flip you get from hanging the strip by its cut edge.
CJK_GLYPH_ROTATION = 90

SHEAR_FACTOR = 0.22  # italic slant amount
FILL_RATIO = 0.92  # glyph height as a fraction of the ribbon width, always maximized to this

PREVIEW_COLUMNS = 48  # terminal columns the ribbon width is squeezed into
PREVIEW_LINE_DELAY = 0.02  # seconds between lines, to feel like it's chugging out


def load_font(size, candidates=FONT_CANDIDATES):
    for path, index in candidates:
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


def is_cjk(ch):
    cp = ord(ch)
    return (
        0x4E00 <= cp <= 0x9FFF  # CJK Unified Ideographs
        or 0x3400 <= cp <= 0x4DBF  # CJK Unified Ideographs Extension A
        or 0x3000 <= cp <= 0x303F  # CJK punctuation
        or 0xFF00 <= cp <= 0xFFEF  # Fullwidth forms
    )


def split_runs(text):
    """Group consecutive characters into (is_cjk, substring) runs."""
    runs = []
    for ch in text:
        cjk = is_cjk(ch)
        if runs and runs[-1][0] == cjk:
            runs[-1] = (cjk, runs[-1][1] + ch)
        else:
            runs.append((cjk, ch))
    return runs


def fit_run(text, candidates, target_h):
    """Pick a font size for `text` so its glyphs are about target_h tall."""
    probe_size = 200
    bbox = measure(load_font(probe_size, candidates), text)
    scale = target_h / (bbox[3] - bbox[1])
    size = max(1, round(probe_size * scale))
    font = load_font(size, candidates)
    bbox = measure(font, text)
    return font, bbox


def render_cjk_run(text, cell, bg_fill, text_fill):
    """Draw CJK glyphs as a row of square cells, each pre-rotated upright."""
    font = load_font(cell, CJK_FONT_CANDIDATES)
    strip = Image.new("L", (cell * len(text), cell), color=bg_fill)
    for i, ch in enumerate(text):
        tile = Image.new("L", (cell, cell), color=bg_fill)
        tile_draw = ImageDraw.Draw(tile)
        bbox = tile_draw.textbbox((0, 0), ch, font=font)
        x = (cell - (bbox[2] - bbox[0])) // 2 - bbox[0]
        y = (cell - (bbox[3] - bbox[1])) // 2 - bbox[1]
        tile_draw.text((x, y), ch, font=font, fill=text_fill)
        tile = tile.rotate(CJK_GLYPH_ROTATION, expand=True, fillcolor=bg_fill)
        strip.paste(tile, (i * cell, 0))
    return strip


def plan_runs(runs, target_h):
    """Size every run to a common visual height: (cjk, text, font/cell, bbox, width)."""
    plan = []
    for cjk, run_text in runs:
        if cjk:
            # CJK glyphs are square, so the cell side is the height itself.
            cell = max(1, int(round(target_h)))
            plan.append((True, run_text, cell, None, cell * len(run_text)))
        else:
            font, bbox = fit_run(run_text, FONT_CANDIDATES, target_h)
            plan.append((False, run_text, font, bbox, int(bbox[2] - bbox[0])))
    return plan


def build_banner_image(text, white_on_black=False, length_cm=DISPLAY_LENGTH_CM):
    text = text.upper()
    bg_fill = 0 if white_on_black else 255
    text_fill = 255 if white_on_black else 0

    runs = split_runs(text)
    target_h = PAPER_WIDTH_PX * FILL_RATIO
    px_per_cm = DPI / 2.54
    max_w = length_cm * px_per_cm

    # Always maximize letter height first, per run (each script/font pair
    # needs its own point size to land on the same visual height).
    plan = plan_runs(runs, target_h)
    total_w = sum(run[4] for run in plan)

    # Shrink every run by the same factor if that made it print longer than
    # length_cm -- otherwise the max-height sizing above stands.
    if total_w > max_w:
        plan = plan_runs(runs, target_h * max_w / total_w)
        total_w = sum(run[4] for run in plan)

    canvas = Image.new("L", (int(total_w), PAPER_WIDTH_PX), color=bg_fill)
    draw = ImageDraw.Draw(canvas)
    x_cursor = 0
    for cjk, run_text, font_or_cell, bbox, run_w in plan:
        if cjk:
            strip = render_cjk_run(run_text, font_or_cell, bg_fill, text_fill)
            canvas.paste(strip, (x_cursor, (PAPER_WIDTH_PX - strip.height) // 2))
        else:
            run_h = int(bbox[3] - bbox[1])
            x = x_cursor - bbox[0]
            y = (PAPER_WIDTH_PX - run_h) // 2 - bbox[1]
            draw.multiline_text((x, y), run_text, font=font_or_cell, fill=text_fill, align="center")
        x_cursor += run_w

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
    parser.add_argument(
        "--length",
        type=float,
        default=DISPLAY_LENGTH_CM,
        help=f"Max printed length in cm (default: {DISPLAY_LENGTH_CM}).",
    )
    args = parser.parse_args()

    text = " ".join(args.text) if args.text else TEXT
    image = build_banner_image(text, white_on_black=args.white_on_black, length_cm=args.length)

    if args.preview:
        print_terminal_preview(image)
    else:
        try:
            p = Usb(VENDOR_ID, PRODUCT_ID, profile=PROFILE)
        except TypeError:
            # Older python-escpos versions don't accept a profile kwarg.
            p = Usb(VENDOR_ID, PRODUCT_ID)
        p.image(image)
        # p.cut()
