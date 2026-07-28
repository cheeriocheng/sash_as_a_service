"""
Prints text vertically down the receipt, styled after Barbara Kruger
"""

import argparse

from PIL import Image, ImageDraw, ImageFont
from escpos.printer import Usb

# ---- Edit me ----
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

# Kruger's typeface is Futura Bold (Oblique). macOS ships Futura.ttc but
# not a bold-oblique instance, so we take the Bold weight and shear it
# ourselves. Falls back to other bold fonts if Futura isn't available.
FONT_CANDIDATES = [
    ("/System/Library/Fonts/Supplemental/Futura.ttc", 2),  # Futura Bold
    ("/System/Library/Fonts/Supplemental/Arial Bold Italic.ttf", 0),
    ("/System/Library/Fonts/Supplemental/HelveticaNeue.ttc", 0),
]

SHEAR_FACTOR = 0.22  # italic slant amount
FILL_RATIO = 0.90  # how much of PAPER_WIDTH_PX the glyph height fills
PADDING_RATIO = 0.06  # margin before/after the text, along the feed direction


def load_font(size):
    for path, index in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size, index=index)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def measure(font, text):
    tmp = ImageDraw.Draw(Image.new("L", (1, 1)))
    return tmp.multiline_textbbox((0, 0), text, font=font, align="center")


def build_banner_image(text, white_on_black=False):
    text = text.upper()
    bg_fill = 0 if white_on_black else 255
    text_fill = 255 if white_on_black else 0

    # Pick a font size so the text's height fills FILL_RATIO of the paper width.
    probe_size = 200
    bbox = measure(load_font(probe_size), text)
    scale = (PAPER_WIDTH_PX * FILL_RATIO) / (bbox[3] - bbox[1])
    size = max(1, round(probe_size * scale))
    font = load_font(size)
    bbox = measure(font, text)
    text_w = int(bbox[2] - bbox[0])
    text_h = int(bbox[3] - bbox[1])

    padding = int(PAPER_WIDTH_PX * PADDING_RATIO)
    canvas = Image.new("L", (text_w + padding * 2, PAPER_WIDTH_PX), color=bg_fill)
    draw = ImageDraw.Draw(canvas)
    x = padding - bbox[0]
    y = (PAPER_WIDTH_PX - text_h) // 2 - bbox[1]
    draw.multiline_text((x, y), text, font=font, fill=text_fill, align="center")

    # Shear for the oblique/italic look.
    w, h = canvas.size
    x_shift = int(round(abs(SHEAR_FACTOR) * h))
    coeffs = (1, SHEAR_FACTOR, -x_shift if SHEAR_FACTOR >= 0 else 0, 0, 1, 0)
    sheared = canvas.transform((w + x_shift, h), Image.AFFINE, coeffs, fillcolor=bg_fill)

    # Rotate so the text reads going down the strip as the paper feeds.
    return sheared.rotate(-90, expand=True, fillcolor=bg_fill)


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
    args = parser.parse_args()

    text = " ".join(args.text) if args.text else TEXT
    image = build_banner_image(text, white_on_black=args.white_on_black)
    p = Usb(VENDOR_ID, PRODUCT_ID, profile=PROFILE)
    p.image(image)
    # p.cut()
