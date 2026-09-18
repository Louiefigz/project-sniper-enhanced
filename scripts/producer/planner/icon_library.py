#!/usr/bin/env python3
"""icon_library — fetch + cache real brand icons as recolored SVGs for chip-row.

The chip-row motion template (MG-3) shows named entities as pills. Operator
calibration: the pills should carry the REAL brand mark (Codex, Gemini, GitHub…)
"scaled, fitting the screen, not obtrusive" — not a generic accent dot. This
module is the build-time fetcher/cache that produces those marks.

Source
------
Simple Icons CDN (https://cdn.simpleicons.org/<slug>) — single-path monochrome
brand marks. Simple Icons is CC0 1.0; the marks themselves are trademarks of
their owners, so the posture here is EDITORIAL USE (identifying the entity a
chip names), recorded per-icon in ``manifest.json``.

Recolor: why local fill-rewrite, not the CDN color endpoint or a CSS filter
---------------------------------------------------------------------------
Operator wants the marks in brand-accent blue (``--accent`` #054BC9) so the row
reads as one system, exactly like the accent dot they replace. Three ways to get
there; two are broken, so we use the third:

* CDN color endpoint ``/<slug>/<hex>`` — UNRELIABLE per-brand. Verified
  2026-07-05: ``openai/054BC9``, ``linkedin/054BC9``, ``slack/054BC9`` all 404
  while the plain ``/<slug>`` default returns 200. openai is the exact mark
  "Codex" needs, so this path is disqualified.
* CSS ``filter`` on the ``<img>`` — cannot reproduce an EXACT hex from black;
  the brightness/sepia/hue-rotate solvers only approximate. Rejected.
* Local fill-rewrite (used here) — fetch the reliable default SVG, rewrite its
  root ``fill`` to the accent hex. Exact, deterministic, one code path for every
  brand, and it keeps the ``<img src="/icons/…">`` render path the template uses
  (no engine-specific mask-mode / currentColor caveats). The accent is baked at
  fetch time; a per-render accent override won't recolor a baked mark, but the
  accent is the fixed brand blue — re-fetch with ``--color <hex>`` for another.

Cache & honesty
---------------
Marks land at ``templates/motion/icons/<name>.svg`` (reachable at ``/icons/<name>.svg``
under the hyperframes web root) with a ``manifest.json`` entry. Names resolve
through ``SLUG_MAP`` (curated) or an explicit ``--slug``. Per repo doctrine we
NEVER fuzzy-match: an unknown name errors and lists the available names; a slug
the CDN 404s errors loudly (see ``KNOWN_UNAVAILABLE`` for brands Simple Icons has
removed on trademark request).
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

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(SCRIPT_DIR))  # producer root (CLI runs)
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "..", ".."))
MOTION_DIR = os.path.join(REPO_ROOT, "templates", "motion")
ICONS_DIR = os.path.join(MOTION_DIR, "icons")
MANIFEST_PATH = os.path.join(ICONS_DIR, "manifest.json")

CDN_BASE = "https://cdn.simpleicons.org"
# Brand accent — must match tokens.css `--accent`. Baked into each cached mark.
ACCENT = "#054BC9"
_UA = "PROJECT-SNIPER-icon-library/1.0"
_TIMEOUT = 20
_RETRIES = 3
LICENSE = ("Simple Icons (CC0 1.0); brand marks are trademarks of their owners "
           "— editorial use only")

# Curated friendly-name -> Simple Icons slug. Every slug here is verified LIVE on
# the CDN (2026-07-05). `codex` is an alias onto the openai mark per the operator.
# This is a data catalog (O(1) lookup) — grow it freely; it is exempt from the
# logic line limit. Add a name only after confirming `fetch <name>` returns 200.
SLUG_MAP = {
    # AI models / tools
    "codex": "openai",          # operator alias: Codex chip uses the OpenAI mark
    "openai": "openai",
    "gemini": "googlegemini",
    "googlegemini": "googlegemini",
    "anthropic": "anthropic",
    "claude": "claude",
    "cursor": "cursor",
    "perplexity": "perplexity",
    "huggingface": "huggingface",
    "replicate": "replicate",
    "langchain": "langchain",
    "ollama": "ollama",
    # Dev / platforms
    "github": "github",
    "docker": "docker",
    "vercel": "vercel",
    "nextjs": "nextdotjs",
    "react": "react",
    "python": "python",
    "figma": "figma",
    "notion": "notion",
    "discord": "discord",
    "google": "google",
    "googlecloud": "googlecloud",
    "meta": "meta",
    "apple": "apple",
    # Social platforms the pipeline publishes to
    "x": "x",
    "twitter": "x",
    "tiktok": "tiktok",
    "instagram": "instagram",
    "youtube": "youtube",
    "facebook": "facebook",
    "whatsapp": "whatsapp",
    "telegram": "telegram",
}

# Brands Simple Icons has REMOVED (trademark/brand requests) — no free mark
# exists. Verified 2026-07-05. Kept so fetch errors are specific, not fuzzy.
KNOWN_UNAVAILABLE = {
    "linkedin": "removed from Simple Icons on brand request — no free mark",
    "slack": "removed from Simple Icons on brand request — no free mark",
    "midjourney": "not in Simple Icons",
    "azure": "not in Simple Icons (microsoftazure/microsoft slugs 404)",
    "aws": "not in Simple Icons (amazonaws/amazonwebservices slugs 404)",
}


def available_names() -> list[str]:
    """Sorted list of curated names that ``fetch`` accepts without ``--slug``."""
    return sorted(SLUG_MAP)


def _cdn_url(slug: str) -> str:
    """Default (brand-colored) CDN URL for ``slug``. We recolor locally, so we
    never hit the flaky ``/<slug>/<hex>`` color endpoint."""
    return f"{CDN_BASE}/{slug}"


def _resolve_slug(name: str, slug_override: str | None) -> str:
    """Map ``name`` to a Simple Icons slug. Explicit ``--slug`` wins; otherwise
    look up ``SLUG_MAP``. NEVER fuzzy-match — an unknown name raises with the
    list of available names (and a specific note for known-removed brands)."""
    if slug_override:
        return slug_override
    key = name.strip().lower()
    if key in SLUG_MAP:
        return SLUG_MAP[key]
    if key in KNOWN_UNAVAILABLE:
        raise ValueError(
            f"'{name}': {KNOWN_UNAVAILABLE[key]}. Pass an explicit --slug if you "
            f"have found a live Simple Icons slug for it.")
    raise ValueError(
        f"unknown icon name '{name}'. Available: {', '.join(available_names())}. "
        f"Or pass --slug <simpleicons-slug> explicitly.")


def _fetch_svg(slug: str) -> str:
    """GET the default SVG for ``slug`` from the CDN. Retries transient network
    errors; a 404 (dead slug) fails immediately and loudly — no fuzzy fallback."""
    url = _cdn_url(slug)
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    last_err: Exception | None = None
    for attempt in range(1, _RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                body = resp.read().decode("utf-8")
            if "<svg" not in body:
                raise ValueError(f"CDN returned non-SVG body for slug '{slug}'")
            return body
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise ValueError(
                    f"slug '{slug}' is not on Simple Icons (404 at {url}). "
                    f"The mark may have been removed on a brand request.") from exc
            last_err = exc
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            last_err = exc
        if attempt < _RETRIES:
            time.sleep(0.6 * attempt)  # linear backoff for transient failures
    raise RuntimeError(f"failed to fetch slug '{slug}' from {url}: {last_err}")


def _recolor(svg: str, color: str | None) -> str:
    """Rewrite the mark's root ``fill`` to ``color`` (e.g. the accent hex).

    Simple Icons default SVGs carry one explicit ``fill="#hex"`` on the root
    ``<svg>``; replacing the first occurrence recolors the whole single-path
    mark. ``color=None`` keeps the native brand color. If no ``fill`` is present
    (mark uses currentColor), inject one on the root tag so ``<img>`` renders the
    intended color rather than the browser default (black)."""
    if color is None:
        return svg
    svg, n = re.subn(r'fill="#[0-9A-Fa-f]{3,8}"', f'fill="{color}"', svg, count=1)
    if n == 0:
        svg = re.sub(r"<svg\b", f'<svg fill="{color}"', svg, count=1)
    return svg


def _load_manifest() -> dict:
    """Load ``manifest.json`` ({name: entry}); tolerate absent/legacy files."""
    if not os.path.isfile(MANIFEST_PATH):
        return {}
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("icons", data) if isinstance(data, dict) else {}


def _save_manifest(icons: dict) -> None:
    """Write ``manifest.json`` sorted by name (stable diffs) with license note."""
    payload = {"license": LICENSE, "source": CDN_BASE,
               "icons": dict(sorted(icons.items()))}
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=True)
        f.write("\n")


def fetch_icon(name: str, slug: str | None = None,
               color: str | None = ACCENT) -> dict:
    """Fetch, recolor, and cache one brand mark; upsert its manifest entry.

    Returns the manifest entry ``{name, slug, source_url, fetched, color,
    license, file}``. Raises ``ValueError`` for an unknown name or a dead slug.
    """
    resolved = _resolve_slug(name, slug)
    svg = _recolor(_fetch_svg(resolved), color)
    os.makedirs(ICONS_DIR, exist_ok=True)
    filename = f"{name.strip().lower()}.svg"
    with open(os.path.join(ICONS_DIR, filename), "w", encoding="utf-8") as f:
        f.write(svg)
    entry = {
        "name": name.strip().lower(),
        "slug": resolved,
        "source_url": _cdn_url(resolved),
        "fetched": datetime.date.today().isoformat(),
        "color": color or "native",
        "license": LICENSE,
        "file": filename,
    }
    icons = _load_manifest()
    icons[entry["name"]] = entry
    _save_manifest(icons)
    return entry


def resolve_name(name: str) -> str:
    """Combined icon resolution for comp specs (iconN / iconFile values).

    ORDER (the dedupe rule): a Simple Icons BRAND mark wins — cached first,
    then fetchable via ``SLUG_MAP`` — and the vendored Lucide GLYPH subset
    (planner/icon_lucide.py) is the fallback for generic needs
    (check/arrow/database/…), returned as ``"lucide/<name>"``. A name in both
    (e.g. ``github``) resolves to the brand mark; ask for ``lucide/github``
    explicitly to force the glyph. Unknown names raise with both vocabularies
    — never fuzzy-matched.
    """
    from planner import icon_lucide  # local: icon_lucide imports our ACCENT
    key = name.strip().lower()
    if key.startswith("lucide/"):               # explicit glyph override
        return icon_lucide.resolve(key[len("lucide/"):])
    if key in _load_manifest():
        return key                              # cached brand mark
    if key in SLUG_MAP:
        fetch_icon(key)                         # cacheable brand mark
        return key
    if key in icon_lucide.LUCIDE_NAMES:
        return icon_lucide.resolve(key)         # vendored glyph
    note = f" ({KNOWN_UNAVAILABLE[key]})" if key in KNOWN_UNAVAILABLE else ""
    raise ValueError(
        f"unknown icon '{name}'{note}. Brand marks: {', '.join(available_names())}. "
        f"Lucide glyphs: {', '.join(sorted(icon_lucide.LUCIDE_NAMES))}.")


def _cmd_resolve(args: argparse.Namespace) -> int:
    """CLI ``resolve``: print the comp-spec iconFile value for a name."""
    print(resolve_name(args.name))
    return 0


def _cmd_fetch(args: argparse.Namespace) -> int:
    """CLI ``fetch``: cache one mark; print where it landed."""
    color = None if args.brand else args.color
    entry = fetch_icon(args.name, slug=args.slug, color=color)
    where = os.path.relpath(os.path.join(ICONS_DIR, entry["file"]), REPO_ROOT)
    print(f"fetched {entry['name']} (slug={entry['slug']}, color={entry['color']}) "
          f"-> {where}")
    return 0


def _cmd_list(_args: argparse.Namespace) -> int:
    """CLI ``list``: cached marks first, then the curated names ``fetch`` knows."""
    icons = _load_manifest()
    if icons:
        print("cached:")
        for name, e in sorted(icons.items()):
            print(f"  {name:<14} slug={e.get('slug'):<14} color={e.get('color')}")
    else:
        print("cached: (none)")
    print("\navailable names (fetch <name>):")
    print("  " + ", ".join(available_names()))
    if KNOWN_UNAVAILABLE:
        print("\nunavailable on Simple Icons (removed / absent):")
        for name, why in sorted(KNOWN_UNAVAILABLE.items()):
            print(f"  {name:<12} {why}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Argparse entry: ``fetch <name> [--slug] [--color] [--brand]`` | ``list``."""
    parser = argparse.ArgumentParser(description="Brand-icon library for chip-row.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_fetch = sub.add_parser("fetch", help="fetch + cache one brand mark")
    p_fetch.add_argument("name", help="friendly name (SLUG_MAP key) or free label")
    p_fetch.add_argument("--slug", help="explicit Simple Icons slug (overrides map)")
    p_fetch.add_argument("--color", default=ACCENT,
                         help=f"hex fill to bake (default accent {ACCENT})")
    p_fetch.add_argument("--brand", action="store_true",
                         help="keep the native brand color (skip accent recolor)")
    p_fetch.set_defaults(func=_cmd_fetch)

    sub.add_parser("list", help="show cached + available names").set_defaults(
        func=_cmd_list)

    p_resolve = sub.add_parser(
        "resolve", help="resolve a name to an iconFile ref (brand > lucide)")
    p_resolve.add_argument("name")
    p_resolve.set_defaults(func=_cmd_resolve)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
