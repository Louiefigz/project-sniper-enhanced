#!/usr/bin/env python3
"""
VENDORED 2026-07-05 from the operator-supplied video-editor sibling project
(workflows/bake-emoji.py). See PRODUCER_EDGE_CASES.md G20 for the deadlock this
prevents.

bake-emoji.py — bake emoji glyphs to trimmed PNGs so the headless render never font-resolves a live emoji.

Raw emoji codepoints DEADLOCK the HyperFrames headless render (a font-load hang that never errors or
times out — see workflows/incremental-graphics.md, the emoji gotcha). The fix is to never put an emoji
in graphic markup: either fake the look in the embedded brand font, or bake the glyph to a PNG here and
overlay it as an <img>.

Renders Apple Color Emoji via PIL (embedded_color) at the only supported sbix strike (160), trims to the
drawn pixels, then re-centers on a square with even padding.

Usage:
    python3 bake-emoji.py <name>=<emoji> [<name>=<emoji> ...] [--out DIR]

    python3 bake-emoji.py rocket=🚀 check=✅ palette=🎨
    python3 bake-emoji.py intake=📥 --out ./assets/emoji

Writes <out>/<name>.png for each pair. Default out: ./assets/emoji next to the cwd.
"""
import os
import sys
import pathlib
from PIL import Image, ImageFont, ImageDraw

# Color-emoji font, by platform. Apple Color Emoji on macOS; Segoe UI Emoji on Windows; Noto Color
# Emoji on Linux/WSL (apt install fonts-noto-color-emoji). First one that exists wins.
EMOJI_FONT_CANDIDATES = [
    "/System/Library/Fonts/Apple Color Emoji.ttc",          # macOS
    "C:\\Windows\\Fonts\\seguiemj.ttf",                      # Windows (Segoe UI Emoji)
    "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",    # Linux / WSL (fonts-noto-color-emoji)
]
STRIKE = 160        # Apple Color Emoji ships specific bitmap strikes; 160 is the largest valid one
DRAW = 320          # generous draw canvas so the glyph never clips while drawing (anchor mm rides high)
PAD_FRAC = 0.12     # even breathing room around the trimmed glyph


def parse_args(argv):
    pairs, out = [], pathlib.Path("assets/emoji")
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--out":
            out = pathlib.Path(argv[i + 1]); i += 2; continue
        if "=" not in a:
            sys.exit("each arg must be name=emoji (got %r)" % a)
        name, glyph = a.split("=", 1)
        pairs.append((glyph, name)); i += 1
    if not pairs:
        sys.exit(__doc__)
    return pairs, out


def bake(glyph, name, font, out_dir):
    big = Image.new("RGBA", (DRAW, DRAW), (0, 0, 0, 0))
    ImageDraw.Draw(big).text((DRAW // 2, DRAW // 2), glyph, font=font, anchor="mm", embedded_color=True)
    bb = big.getbbox()                                      # trim to the actual drawn pixels...
    if bb is None:
        sys.exit("[emoji] %r drew nothing — bad glyph or font missing color strike" % glyph)
    cropped = big.crop(bb)
    side = max(cropped.width, cropped.height)
    pad = int(round(side * PAD_FRAC))
    out_side = side + 2 * pad
    out = Image.new("RGBA", (out_side, out_side), (0, 0, 0, 0))   # ...then re-center on a square w/ even pad
    out.paste(cropped, ((out_side - cropped.width) // 2, (out_side - cropped.height) // 2), cropped)
    out.save(out_dir / (name + ".png"))
    print("[emoji] %s -> %s.png (%dx%d)" % (glyph, name, out_side, out_side))


def main():
    pairs, out_dir = parse_args(sys.argv[1:])
    out_dir.mkdir(parents=True, exist_ok=True)
    emoji_font = next((p for p in EMOJI_FONT_CANDIDATES if os.path.exists(p)), None)
    if emoji_font is None:
        sys.exit("[emoji] no color-emoji font found. Install one:\n"
                 "  Linux/WSL:  sudo apt install fonts-noto-color-emoji\n"
                 "  (macOS/Windows ship one by default.)\n"
                 "Or skip baking and fake the look in your brand font (see workflows/incremental-graphics.md).")
    font = ImageFont.truetype(emoji_font, STRIKE)
    for glyph, name in pairs:
        bake(glyph, name, font, out_dir)
    print("done ->", out_dir)


if __name__ == "__main__":
    main()
