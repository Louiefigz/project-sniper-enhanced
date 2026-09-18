#!/usr/bin/env python3
"""Deterministic glyph-advance width tables for the comp fit gates.

Char-count fit caps assume an AVERAGE glyph; a wide-glyph line ("W" x 40)
passes the count and clips invisibly in the comps' overflow-hidden masks
(adversarial review 2026-08-28, finding F3). These tables carry the real
per-glyph advance widths (em units) of the two comp fonts, measured once in
headless Chrome against the tokens.css @font-face data URIs (10-glyph
repeats at 100px) and baked here so plan-time gates stay deterministic with
no browser in the loop.

Width model: sum of advances plus per-char letter-spacing, scaled by the
font size, times a small safety factor for cross-glyph kerning drift (the
summed tables sit within ~0.5% of whole-string browser measurements).
Unmeasured glyphs assume a wide 1.1em advance — fail closed, never clip.
"""
from __future__ import annotations

_SAFETY = 1.02
_UNKNOWN_EM = 1.1

# ---- measured advance tables (data catalogs — exempt from line budget) ---- #
# Inter weight 600 — the house --font (line-swap lines, marker panel text).
INTER_600 = {
    " ": 0.237, "i": 0.271, "j": 0.271, "l": 0.271, "I": 0.281, ".": 0.334,
    ",": 0.334, ":": 0.334, "!": 0.338, "'": 0.339, ";": 0.343, "t": 0.357,
    "f": 0.361, "(": 0.377, ")": 0.377, "[": 0.377, "]": 0.377, "/": 0.388,
    "r": 0.414, "1": 0.431, "-": 0.468, "_": 0.476, '"': 0.552, "*": 0.559,
    "s": 0.56, "?": 0.56, "L": 0.565, "z": 0.573, "k": 0.58, "x": 0.58,
    "a": 0.581, "J": 0.584, "F": 0.587, "c": 0.588, "e": 0.596, "7": 0.599,
    "v": 0.6, "y": 0.602, "E": 0.607, "o": 0.613, "5": 0.622, "h": 0.623,
    "n": 0.623, "u": 0.623, "2": 0.63, "b": 0.63, "d": 0.63, "p": 0.63,
    "q": 0.63, "g": 0.632, "3": 0.646, "P": 0.648, "6": 0.649, "9": 0.649,
    "#": 0.649, "8": 0.651, "S": 0.655, "$": 0.655, "R": 0.657, "B": 0.662,
    "Z": 0.664, "T": 0.667, "&": 0.672, "0": 0.674, "4": 0.676, "+": 0.679,
    "=": 0.679, "<": 0.679, ">": 0.679, "K": 0.719, "D": 0.722, "Y": 0.731,
    "U": 0.732, "X": 0.738, "C": 0.74, "H": 0.747, "G": 0.751, "A": 0.76,
    "V": 0.76, "N": 0.762, "O": 0.771, "Q": 0.777, "w": 0.85, "m": 0.913,
    "M": 0.932, "%": 1.016, "@": 1.016, "W": 1.057,
}

# Caveat weight 700 — the hand font (hw-callout label).
CAVEAT_700 = {
    "'": 0.216, " ": 0.255, ".": 0.265, ",": 0.265, ":": 0.265, ";": 0.265,
    "j": 0.272, "I": 0.279, "J": 0.279, "!": 0.312, '"': 0.325, "l": 0.327,
    "i": 0.328, "t": 0.352, "-": 0.358, "e": 0.377, "r": 0.391, "?": 0.392,
    "f": 0.412, "_": 0.412, "(": 0.418, ")": 0.418, "[": 0.418, "]": 0.418,
    "o": 0.427, "c": 0.431, "/": 0.432, "s": 0.454, "p": 0.468, "x": 0.481,
    "b": 0.485, "v": 0.494, "a": 0.515, "1": 0.525, "h": 0.533, "0": 0.545,
    "9": 0.545, "*": 0.553, "z": 0.556, "8": 0.565, "F": 0.565, "d": 0.567,
    "P": 0.57, "g": 0.6, "3": 0.603, "q": 0.603, "&": 0.606, "5": 0.609,
    "T": 0.612, "u": 0.618, "E": 0.621, "2": 0.622, "k": 0.626, "4": 0.628,
    "C": 0.629, "#": 0.63, "6": 0.636, "L": 0.637, "D": 0.646, "X": 0.653,
    "V": 0.654, "y": 0.661, "n": 0.67, "$": 0.672, "w": 0.678, "Y": 0.681,
    "7": 0.682, "B": 0.685, "@": 0.685, "%": 0.71, "O": 0.72, "A": 0.727,
    "Q": 0.737, "U": 0.737, "S": 0.743, "G": 0.749, "K": 0.755, "H": 0.758,
    "R": 0.762, "N": 0.781, "+": 0.833, "=": 0.833, "<": 0.833, ">": 0.833,
    "M": 0.878, "m": 0.901, "Z": 0.907, "W": 0.983,
}


def text_width_px(text: str, table: dict[str, float], font_px: float,
                  letter_spacing_em: float = 0.0) -> float:
    """Estimated painted width of one nowrap line, in px (safety included).

    Args:
        text: The line exactly as the comp will paint it.
        table: One of the measured advance tables above.
        font_px: The comp's resolved font size in px.
        letter_spacing_em: The comp's letter-spacing (em; may be negative).

    Returns:
        The conservative painted width in px.
    """
    advances = sum(table.get(char, _UNKNOWN_EM) for char in text)
    advances += letter_spacing_em * len(text)
    return advances * font_px * _SAFETY
