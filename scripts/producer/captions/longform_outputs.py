#!/usr/bin/env python3
"""longform_outputs — sidecar SRT + YouTube chapters for long-form mode.

Stage 5 of the PRODUCER renderer for LONGFORM mode (see docs/producer/PRODUCER_PLAN.md
§4.2 stage 5 + §3.1 doctrine): long-form ships a 16:9 master with a sidecar
``.srt`` and a ``chapters.txt`` rather than burned karaoke captions. Both
derive deterministically from the kept words (which arrive ALREADY REMAPPED to
OUTPUT time by ``compile_timeline.remap_words``) and the plan's chapter list —
nothing here is brain-authored.

The SRT REUSES captions.py's grouping + windowing + wrapping wholesale (import,
never duplicate): same blocks a burned track would use, same sentence-aware
capitalization, same ≤2-line wrap — only the emission differs (line text, SRT
timecodes, no karaoke ``\\k`` tags). Several captions helpers are private
(underscore-prefixed); we import them anyway rather than fork the grouping
logic, so the sidecar can never drift from the burned track.

Chapters follow YouTube's rules: ``MM:SS Title`` (``H:MM:SS`` past an hour), one
per line; the first MUST sit at 0:00 (we prepend "0:00 Intro" and warn if the
plan's first chapter doesn't), and YouTube only renders a chapter list with ≥3
chapters each ≥10s apart — we warn on a violation but never fail the render.

CLI: longform_outputs.py <words.json> <out.srt> [--chapters chapters.json out.txt]
  words.json    = [{"word": str, "start": float, "end": float}, ...] in OUTPUT time.
  chapters.json = [{"outStart": float, "title": str}, ...] in OUTPUT time.
"""

from __future__ import annotations

import json
import sys

# Import the captions grouping/windowing/wrapping wholesale so the sidecar SRT
# stays byte-for-byte consistent with the burned track's block boundaries and
# capitalization. Private (underscore) helpers are imported deliberately —
# forking group_words' logic here would let the two tracks diverge (the exact
# thing captions.py's module docstring warns against). group_words is public;
# _merge_punctuation / _block_windows / _block_caps / _display_texts /
# _wrap_indices are its private collaborators, reused not reimplemented.
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # run-by-path: producer pkg root on sys.path
from captions.captions_ass import (  # noqa: F401  (private imports are intentional — see above)
    _block_caps,
    _block_windows,
    _display_texts,
    _merge_punctuation,
    _wrap_indices,
    group_words,
)
from producer_config import CAPTIONS


# ---------------------------------------------------------------------------
# SRT sidecar — line captions (no karaoke), reusing captions.py grouping
# ---------------------------------------------------------------------------
def _srt_time(t: float) -> str:
    """Seconds → SRT ``HH:MM:SS,mmm`` (millisecond precision, comma separator)."""
    ms = max(0, int(round(t * 1000)))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _cue_text(block: list[dict], capitalize_first: bool) -> str:
    """Render one block as SRT cue text: ≤2 wrapped lines, verbatim words.

    Mirrors captions._render_line but emits plain ``\\n`` line breaks and skips
    ASS override escaping (SRT is plain text). Capitalization is sentence-aware
    via the shared ``_display_texts`` contract.
    """
    texts = _display_texts(block, capitalize_first)
    lines = _wrap_indices(texts, CAPTIONS["max_chars_per_line"])
    return "\n".join(" ".join(texts[i] for i in ln) for ln in lines)


def _srt_cues(words: list[dict]) -> list[str]:
    """Group + window + wrap the words into a list of SRT cue strings.

    Uses the shared captions.py helpers so blocks match a burned track exactly.
    Each cue is guaranteed ``end > start`` (``_block_windows`` floors it) and
    ≤2 lines (``group_words`` enforces ``max_lines``).
    """
    clean = _merge_punctuation(words)
    blocks = group_words(clean, CAPTIONS)
    windows = _block_windows(blocks, CAPTIONS)
    caps = _block_caps(blocks)
    return [
        f"{i}\n{_srt_time(s)} --> {_srt_time(e)}\n{_cue_text(b, cap)}\n"
        for i, (b, (s, e), cap) in enumerate(zip(blocks, windows, caps), start=1)
    ]


def build_srt(words: list[dict]) -> str:
    """Compile output-time words into a complete SRT document string."""
    return "\n".join(_srt_cues(words))


def write_srt(words: list[dict], out_path: str) -> int:
    """Write a sidecar SRT for the given output-time words; return cue count.

    Args:
        words: Kept words remapped to OUTPUT time — ``[{"word", "start", "end"}]``.
        out_path: Destination ``.srt`` path.

    Returns:
        The number of cues written.
    """
    cues = _srt_cues(words)
    with open(out_path, "w") as f:
        f.write("\n".join(cues))
    return len(cues)


# ---------------------------------------------------------------------------
# YouTube chapters — "MM:SS Title" (H:MM:SS past an hour), first at 0:00
# ---------------------------------------------------------------------------
def _chapter_time(t: float) -> str:
    """Seconds → YouTube chapter stamp: ``M:SS``, or ``H:MM:SS`` past an hour.

    Minutes are unpadded below an hour so ``t=0`` renders the required literal
    ``0:00``; seconds always zero-pad. Floored to whole seconds (YouTube
    chapter stamps have no sub-second field).
    """
    total = max(0, int(t))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _warn(msg: str) -> None:
    """Emit a non-fatal chapter warning to stderr (never fails the render)."""
    print(f"[longform_outputs] WARNING: {msg}", file=sys.stderr)


def _ensure_intro_at_zero(items: list[dict]) -> list[dict]:
    """Guarantee a chapter at 0:00 (YouTube requires it); prepend + warn if not."""
    if items and int(items[0]["outStart"]) == 0:
        return items
    _warn("first chapter is not at 0:00 — YouTube requires it; "
          "prepending '0:00 Intro'")
    return [{"outStart": 0.0, "title": "Intro"}, *items]


def _warn_chapter_minimums(items: list[dict]) -> None:
    """Warn (don't fail) on YouTube's ≥3-chapters and ≥10s-apart minimums."""
    if len(items) < 3:
        _warn(f"only {len(items)} chapter(s) — YouTube needs >=3 to render a "
              "chapter list")
    for prev, cur in zip(items, items[1:]):
        if cur["outStart"] - prev["outStart"] < 10.0:
            _warn(f"chapters at {_chapter_time(prev['outStart'])} and "
                  f"{_chapter_time(cur['outStart'])} are <10s apart "
                  "(below YouTube's minimum spacing)")


def build_chapters(chapters: list[dict]) -> str:
    """Compile a plan chapter list into a YouTube ``chapters.txt`` body.

    Sorts by ``outStart``, forces a 0:00 chapter, and warns on YouTube's
    minimums — see :func:`write_chapters`.
    """
    items = sorted(
        ({"outStart": float(c["outStart"]), "title": str(c["title"]).strip()}
         for c in chapters),
        key=lambda c: c["outStart"],
    )
    items = _ensure_intro_at_zero(items)
    _warn_chapter_minimums(items)
    lines = [f"{_chapter_time(c['outStart'])} {c['title']}" for c in items]
    return "\n".join(lines) + "\n"


def write_chapters(chapters: list[dict], out_path: str) -> None:
    """Write a YouTube chapters file from plan chapters (OUTPUT time).

    Args:
        chapters: ``[{"outStart": float, "title": str}, ...]`` in output time.
        out_path: Destination ``chapters.txt`` path.

    Enforces (warn, never fail): a 0:00 first chapter, ≥3 chapters, ≥10s
    spacing. See :func:`build_chapters`.
    """
    with open(out_path, "w") as f:
        f.write(build_chapters(chapters))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _parse_chapters_flag(args: list[str]) -> list[str] | None:
    """Pop ``--chapters <in.json> <out.txt>`` from args; return the pair or None."""
    if "--chapters" not in args:
        return None
    idx = args.index("--chapters")
    pair = args[idx + 1:idx + 3]
    del args[idx:idx + 3]
    return pair


def main() -> None:
    args = sys.argv[1:]
    chapters_args = _parse_chapters_flag(args)
    usage = ("Usage: longform_outputs.py <words.json> <out.srt> "
             "[--chapters chapters.json out.txt]")
    if len(args) != 2 or (chapters_args is not None and len(chapters_args) != 2):
        print(json.dumps({"error": usage}))
        sys.exit(1)
    try:
        with open(args[0]) as f:
            words = json.load(f)
        cues = write_srt(words, args[1])
        result = {"status": "done", "words": len(words),
                  "cues": cues, "srt": args[1]}
        if chapters_args:
            with open(chapters_args[0]) as f:
                chapters = json.load(f)
            write_chapters(chapters, chapters_args[1])
            result["chapters"] = chapters_args[1]
        print(json.dumps(result))
    except (OSError, json.JSONDecodeError, ValueError, KeyError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
