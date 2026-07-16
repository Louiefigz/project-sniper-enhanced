#!/usr/bin/env python3
"""brand — the SINGLE SOURCE OF TRUTH for visual style.

Two catalogs, both read from the repo (never hand-copied), so a renderer can
never invent a look:

* **Color/font tokens** — parsed from ``templates/motion/tokens.css`` (the ONE
  place a brand color or font is defined; the HTML comps read the same file via
  ``var(--token)``). Python reading the same CSS means the pipeline and the comps
  cannot drift apart.
* **Composition catalog** — every ``*.html`` under
  ``templates/motion/compositions/``. A titled graphic MUST be one of these; a
  ``kind`` outside the catalog was invented, not authored (producer-study is the
  only sanctioned path to a new comp).

This module is imported by ``brand_lint`` (the gate) and may be reused anywhere a
color/font/comp must be resolved. It NEVER hardcodes a value it could read.
"""
from __future__ import annotations

import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))          # PROJECT_SNIPER/
TOKENS_CSS = os.path.join(_ROOT, "templates", "motion", "tokens.css")
COMPOSITIONS_DIR = os.path.join(_ROOT, "templates", "motion", "compositions")

# Structural parsers (mechanical WHERE-detection, not semantics): a CSS custom
# property declaration and any 6-digit hex, in either #RRGGBB or ffmpeg 0xRRGGBB
# form (the renderer passes colors to ffmpeg as 0x..., to libass/CSS as #...).
_VAR_RE = re.compile(r"--([a-z0-9-]+)\s*:\s*([^;]+);")
_HEX_RE = re.compile(r"(?:#|0x)([0-9a-fA-F]{6})\b")


def load_tokens() -> dict[str, str]:
    """Parse ``tokens.css`` ``:root`` custom properties into ``{name: value}``.

    Skips the embedded ``@font-face`` base64 blobs (the file is ~1 MB of inlined
    woff2) by ignoring any line carrying font payload — only the short token
    declarations are wanted.
    """
    tokens: dict[str, str] = {}
    with open(TOKENS_CSS, encoding="utf-8", errors="ignore") as f:
        for line in f:
            if "base64" in line or "src:" in line or len(line) > 400:
                continue
            m = _VAR_RE.search(line)
            if m:
                tokens.setdefault(m.group(1).strip(), m.group(2).strip())
    return tokens


def brand_hexes() -> set[str]:
    """Every hex color sanctioned by the tokens, normalized to 6-digit UPPER.

    Any color literal in pipeline code outside this set is drift (my invented
    navy ``0x0e1a2b`` is not here; ``#FFD400`` / ``#054BC9`` are).
    """
    hexes: set[str] = set()
    for value in load_tokens().values():
        for h in _HEX_RE.findall(value):
            hexes.add(h.upper())
    return hexes


def find_hexes(text: str) -> set[str]:
    """All 6-digit hex literals in ``text`` (either #RRGGBB or 0xRRGGBB), UPPER."""
    return {h.upper() for h in _HEX_RE.findall(text)}


def registered_comps() -> set[str]:
    """The composition catalog: each ``*.html`` name (no extension) under
    ``compositions/``. A graphic ``kind`` must be a member — otherwise it was
    invented rather than picked from the built, style-locked templates."""
    if not os.path.isdir(COMPOSITIONS_DIR):
        return set()
    return {f[:-5] for f in os.listdir(COMPOSITIONS_DIR) if f.endswith(".html")}


# Comps that render a TITLED/section graphic. A section/title beat must resolve to
# one of these — never a freeform text overlay (the drawtext title I hand-rolled).
TITLE_COMPS = frozenset({
    "section-marker", "section-takeover", "statement-card", "stat-card",
    "kinetic-quote", "kinetic-quote-wide", "fragment-payoff", "logo-card",
})
