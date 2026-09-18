#!/usr/bin/env python3
"""icon_lucide — vendor + resolve a curated Lucide glyph subset (ISC license).

Simple Icons (icon_library.py) covers BRAND marks; cards also need GENERIC
glyphs — check/status/arrow/database/cpu/globe/lock/chart… This module vendors
a curated ~45-icon Lucide subset into ``templates/motion/icons/lucide/`` so
comps reach them at ``/icons/lucide/<name>.svg`` with the exact same
``iconFile`` resolution rule the comps already implement (a bare value without
a dot gets ``.svg`` appended under ``/icons/`` — pass ``"lucide/check"``).

Resolution order / dedupe: ``icon_library.resolve_name`` prefers the Simple
Icons BRAND mark when a name exists in both vocabularies (e.g. ``github``);
the Lucide glyph stays reachable explicitly as ``lucide/github``.

Source & license (recorded per-icon in ``manifest.json`` + PROVENANCE.md):
pinned ``lucide-static@{LUCIDE_VERSION}`` on unpkg. Lucide is ISC-licensed
(portions Feather, MIT) — vendoring with the license recorded is exactly the
intended use. Marks are stroke-based (``stroke="currentColor"``); the fetch
bakes the brand accent into the stroke, mirroring icon_library's fill-rewrite
posture (exact hex, one code path, no CSS-filter approximation).

CLI:
    icon_lucide.py vendor [name ...]   # fetch + recolor the subset (all curated)
    icon_lucide.py list                # curated names + vendored status
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from planner.icon_library import ACCENT, MOTION_DIR  # noqa: E402

LUCIDE_VERSION = "0.525.0"           # pinned — a version bump is a deliberate edit
CDN_BASE = f"https://unpkg.com/lucide-static@{LUCIDE_VERSION}/icons"
LUCIDE_DIR = os.path.join(MOTION_DIR, "icons", "lucide")
MANIFEST_PATH = os.path.join(LUCIDE_DIR, "manifest.json")
LICENSE = ("Lucide (ISC; portions of Lucide are Feather, MIT) — "
           f"lucide-static@{LUCIDE_VERSION}")
_UA = "PROJECT-SNIPER-icon-lucide/1.0"
_TIMEOUT = 20
_RETRIES = 3

# Curated subset (data catalog — exempt from logic line limits). Every name is
# a live lucide-static icon file, verified against the pinned version at
# vendor time (a 404 fails loudly; fix the name, never fuzzy-match).
LUCIDE_NAMES: tuple[str, ...] = (
    # check / status
    "check", "circle-check", "x", "circle-x", "triangle-alert", "circle-alert",
    "info",
    # arrows / flow
    "arrow-right", "arrow-left", "arrow-up", "arrow-down", "arrow-up-right",
    "chevron-right", "refresh-cw",
    # infra / dev
    "database", "server", "cpu", "hard-drive", "cloud", "globe", "terminal",
    "code", "git-branch", "workflow", "github",
    # security
    "lock", "lock-open", "shield", "shield-check", "key",
    # charts / metrics
    "chart-line", "chart-column", "chart-pie", "trending-up", "trending-down",
    "gauge",
    # general card needs
    "zap", "clock", "calendar", "search", "settings", "wrench", "file-text",
    "folder", "user", "users", "dollar-sign", "target", "rocket", "lightbulb",
    "brain", "sparkles", "layers", "box", "link",
)


def ref(name: str) -> str:
    """The comp-spec ``iconFile`` value for a vendored glyph."""
    return f"lucide/{name}"


def _load_manifest() -> dict:
    """{name: entry} from ``manifest.json`` (empty when nothing vendored)."""
    if not os.path.isfile(MANIFEST_PATH):
        return {}
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        return json.load(f).get("icons", {})


def _save_manifest(icons: dict) -> None:
    """Write ``manifest.json`` sorted by name with the license record."""
    payload = {"license": LICENSE, "source": CDN_BASE,
               "version": LUCIDE_VERSION, "icons": dict(sorted(icons.items()))}
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=True)
        f.write("\n")


def vendored() -> set[str]:
    """Names present in the manifest AND on disk (both must hold)."""
    return {n for n in _load_manifest()
            if os.path.isfile(os.path.join(LUCIDE_DIR, f"{n}.svg"))}


def resolve(name: str) -> str:
    """``name`` → ``"lucide/<name>"`` for a VENDORED glyph; raises otherwise.

    Deterministic and offline: resolution never fetches. An un-vendored
    curated name says how to vendor it; an unknown name lists the vocabulary.
    """
    key = name.strip().lower()
    if key in vendored():
        return ref(key)
    if key in LUCIDE_NAMES:
        raise ValueError(f"lucide icon '{key}' is curated but not vendored — "
                         f"run planner/icon_lucide.py vendor {key}")
    raise ValueError(f"unknown lucide icon '{key}'. Curated: "
                     f"{', '.join(sorted(LUCIDE_NAMES))}")


def _fetch_svg(name: str) -> str:
    """GET one icon from the pinned CDN path (retries transient errors; a 404
    — a bad curated name — fails immediately and loudly)."""
    url = f"{CDN_BASE}/{name}.svg"
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    last_err: Exception | None = None
    for attempt in range(1, _RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                body = resp.read().decode("utf-8")
            if "<svg" not in body:
                raise ValueError(f"CDN returned non-SVG body for '{name}'")
            return body
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise ValueError(
                    f"'{name}' is not in lucide-static@{LUCIDE_VERSION} "
                    f"(404 at {url}) — fix the curated name") from exc
            last_err = exc
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            last_err = exc
        if attempt < _RETRIES:
            time.sleep(0.6 * attempt)
    raise RuntimeError(f"failed to fetch '{name}' from {url}: {last_err}")


def _recolor(svg: str, color: str) -> str:
    """Bake ``color`` into the stroke (Lucide marks are stroke-based)."""
    svg, n = re.subn(r'stroke="currentColor"', f'stroke="{color}"', svg, count=1)
    if n == 0:
        raise ValueError("unexpected lucide SVG shape: no stroke=\"currentColor\"")
    return svg


def vendor(names: list[str] | None = None, color: str = ACCENT) -> list[dict]:
    """Fetch, recolor, and vendor the curated subset (or ``names``).

    Unknown names raise BEFORE any fetch. Returns the manifest entries.
    """
    targets = list(names) if names else list(LUCIDE_NAMES)
    unknown = [n for n in targets if n not in LUCIDE_NAMES]
    if unknown:
        raise ValueError(f"not in the curated set: {unknown} — add to "
                         "LUCIDE_NAMES first (verified against the pinned "
                         "version), never vendor ad hoc")
    os.makedirs(LUCIDE_DIR, exist_ok=True)
    icons, entries = _load_manifest(), []
    for name in targets:
        svg = _recolor(_fetch_svg(name), color)
        with open(os.path.join(LUCIDE_DIR, f"{name}.svg"), "w",
                  encoding="utf-8") as f:
            f.write(svg)
        entry = {"name": name, "source_url": f"{CDN_BASE}/{name}.svg",
                 "fetched": datetime.date.today().isoformat(), "color": color,
                 "license": LICENSE, "file": f"{name}.svg"}
        icons[name] = entry
        entries.append(entry)
    _save_manifest(icons)
    return entries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lucide glyph subset vendorer")
    sub = parser.add_subparsers(dest="command", required=True)
    p_vendor = sub.add_parser("vendor", help="fetch + recolor the curated subset")
    p_vendor.add_argument("names", nargs="*", help="subset (default: all curated)")
    p_vendor.add_argument("--color", default=ACCENT,
                          help=f"stroke hex to bake (default accent {ACCENT})")
    sub.add_parser("list", help="curated names + vendored status")
    args = parser.parse_args(argv)
    try:
        if args.command == "vendor":
            entries = vendor(args.names or None, color=args.color)
            print(f"vendored {len(entries)} lucide icons -> "
                  f"{os.path.relpath(LUCIDE_DIR)}")
        else:
            have = vendored()
            for n in sorted(LUCIDE_NAMES):
                print(f"{n:<16} {'vendored' if n in have else 'MISSING'}")
        return 0
    except (ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
