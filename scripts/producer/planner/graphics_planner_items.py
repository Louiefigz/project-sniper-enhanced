#!/usr/bin/env python3
"""graphics_planner_items — structural listed-items scan → whiteboard-map.

The whiteboard-cutaway half of the R14 longform retarget (see
graphics_planner_longform): a sentence carrying 3+ coordinated items — spoken
count or not — earns a FULL-FRAME whiteboard-map cutaway (audit §2 row 4: the
pro's mind-map lands one node per enumerated item, "YouTube comedy channel /
SEO company / AI agency"). Pure word-list analysis, no video. Split out to
keep each file within the 300-logic-line budget.

Overlay-rich (pair-2) tier: the whiteboard-map comp carries 4 node slots, so a
5+-item enumeration overflows it. ``pip_aware_maps`` uses canvas-pip-list only
when that form is executable through deterministic gates. Until its PiP
renderer is wired, long lists fall back to the legal 5-row whiteboard-list.
The classic ``whiteboard_maps`` path is untouched.

No trigger maps to glitch-hit or avatar-bio-card here (or anywhere in MG-4):
glitch-hit is a 400ms operator/brain-only emphasis hit with no transcript
signal, and avatar-bio-card is a once-per-channel intro asset — see
graphics_planner_rules for the full rationale.

PROPOSES only — candidates are reviewed by the brain, vetoed by the operator.
"""

from __future__ import annotations

import string

from graphics.comp_capabilities import is_aspect_legal_kind
from graphics.form_allocation import is_gate_executable_kind
from planner.motion_triggers import _clean, _sentence_starts, _word_text
from producer_config import MOTION

# --------------------------------------------------------------------------- #
# Constants — MOTION-shaped, module-local for now (belong in a future
# producer_config.MOTION["longform_cutaways"] block; see graphics_planner_
# longform for the rationale).
# --------------------------------------------------------------------------- #
MIN_ITEMS = 3                   # R14: 3+ listed items earn the whiteboard
PIP_MIN_ITEMS = 5               # R24: 5+ items overflow the 4-node whiteboard
PIP_MAX_ITEMS = 8               # canvas-pip-list comp carries item1..8 slots
LIST_MAX_ITEMS = 5              # legal whiteboard-list fallback capacity
ITEM_MAX_WORDS = 6              # a middle item is a short noun phrase
LAST_ITEM_MAX_WORDS = 8         # the and/or-led final item, pre-truncation
NODE_MAX_WORDS = 5              # node display text cap (brain refines copy)
TITLE_MAX_WORDS = 8             # framing-phrase display cap
ITEM1_BACKSCAN = 6              # carrier-tail tokens scanned for the opener
WHITEBOARD_EXIT_PAD_S = 1.2     # canvas holds a beat after the last item

# First-item openers: determiners/possessives + wh-words ("a YouTube comedy
# channel", "who you help"). "no" kept — it carries the negation ("no niche").
_OPENERS = frozenset({"a", "an", "the", "my", "our", "your", "his", "her",
                      "their", "no", "some", "who", "what", "why", "how",
                      "where", "when", "which"})
_STRIP_DETERMINERS = frozenset({"a", "an", "the"})


def whiteboard_maps(*args: object, **kwargs: object) -> None:
    """Retired local-template selection; use the upstream catalog."""
    raise ValueError("Legacy list templates are retired; select the HyperFrames catalog")


def pip_aware_maps(ctx) -> list[dict]:
    """Overlay-rich list scan with a deterministic gate-legal fallback.

    ``ctx`` is a graphics_planner_longform.Ctx (duck-typed here to avoid a
    circular import). Same detector as ``whiteboard_maps``; only the template
    routing differs. Long enumerations use the speaker PiP form only when its
    renderer is executable; otherwise they become a 5-row full-frame list."""
    target = (ctx.mode, ctx.out_dur)
    out: list[dict] = []
    for span, items in _list_scan(ctx.words, ctx.state_fn):
        build = (_long_list_candidate if len(items) >= PIP_MIN_ITEMS
                 else _map_candidate)
        out.append(build(ctx.words, span, items, target))
    return out


def _list_scan(words: list[dict], state_fn):
    """Yield (sentence_span, items) for each talking-head 3+-item sentence."""
    cleaned = [_clean(_word_text(w)) for w in words]
    for span in _sentences(words):
        state, _ = state_fn(float(words[span[0]]["start"]))
        # Untagged longform = talking-head (same default as the R14 retarget gate);
        # only an EXPLICIT screen-share zone opts out of the cutaway grammar.
        if (state or "talking-head") != "talking-head":
            continue
        items = _listed_items(words, cleaned, span)
        if items:
            yield span, items


def _sentences(words: list[dict]) -> list[tuple[int, int]]:
    """Inclusive (start, end) word spans of each sentence."""
    starts = _sentence_starts(words)
    spans, begin = [], 0
    for i in range(len(words)):
        if i > begin and starts[i]:
            spans.append((begin, i - 1))
            begin = i
    if words:
        spans.append((begin, len(words) - 1))
    return spans


def _listed_items(words: list[dict], cleaned: list[str],
                  span: tuple[int, int]) -> list[tuple[int, int]] | None:
    """3+ coordinated items in the sentence ``span``, as word-index spans.

    Two shapes fire (both need an unambiguous first-item opener; non-Oxford
    lists — "A, B and C" — don't fire, conservative by design):
      A. and/or coordination: "…launched a YouTube comedy channel, an SEO
         company, and an AI agency." — the rightmost SHORT and/or-led comma
         segment anchors the list, short segments walk back as middle items,
         and the first item is recovered from the carrier segment's tail by
         scanning back to a determiner/wh-word.
      B. anaphora: "no niche, no offer, no idea…" — every run segment opens
         with the SAME token, which also appears in the carrier's tail.
    """
    segs = _segments(words, span)
    if len(segs) < 3:
        return None
    return (_coordination(words, cleaned, segs)
            or _anaphora(cleaned, segs))


def _segments(words: list[dict], span: tuple[int, int]) -> list[tuple[int, int]]:
    """Comma-delimited (start, end) sub-spans of the sentence."""
    segs, begin = [], span[0]
    for k in range(span[0], span[1] + 1):
        if k < span[1] and _word_text(words[k]).rstrip().endswith(","):
            segs.append((begin, k))
            begin = k + 1
    segs.append((begin, span[1]))
    return segs


def _seg_words(seg: tuple[int, int]) -> int:
    return seg[1] - seg[0] + 1


def _coordination(words: list[dict], cleaned: list[str],
                  segs: list[tuple[int, int]]) -> list[tuple[int, int]] | None:
    """Shape A: rightmost short and/or segment anchors the item run."""
    anchor = _anchor_segment(cleaned, segs)
    if anchor is None:
        return None
    items = [(segs[anchor][0] + 1, segs[anchor][1])]    # strip the and/or
    idx = anchor - 1
    while idx >= 1 and _seg_words(segs[idx]) <= ITEM_MAX_WORDS:
        items.insert(0, segs[idx])
        idx -= 1
    first = _item_opener(cleaned, segs[idx])
    if first is None or len(items) + 1 < MIN_ITEMS:
        return None
    return [(first, segs[idx][1])] + items


def _anchor_segment(cleaned: list[str],
                    segs: list[tuple[int, int]]) -> int | None:
    """Index of the rightmost and/or-led segment short enough to be an item."""
    for idx in range(len(segs) - 1, 1, -1):
        s, e = segs[idx]
        if cleaned[s] in ("and", "or") and (e - s) <= LAST_ITEM_MAX_WORDS:
            return idx
    return None


def _anaphora(cleaned: list[str],
              segs: list[tuple[int, int]]) -> list[tuple[int, int]] | None:
    """Shape B: "…no niche, no offer, no idea…" — repeated segment opener.

    The run may start mid-sentence ("…proud of the work, but I had no niche,
    no offer, no idea…"): the TRAILING run of same-lead segments anchors the
    list, and the segment before it is the carrier holding the first item."""
    lead = cleaned[segs[-1][0]]
    if not lead or lead in ("and", "or"):
        return None
    run = len(segs) - 1
    while run > 0 and cleaned[segs[run - 1][0]] == lead:
        run -= 1
    if run == 0 or len(segs) - run < 2:
        return None
    if any(_seg_words(s) > LAST_ITEM_MAX_WORDS for s in segs[run:]):
        return None
    carrier = segs[run - 1]
    tail_lo = max(carrier[0], carrier[1] - ITEM1_BACKSCAN + 1)
    hits = [k for k in range(tail_lo, carrier[1] + 1) if cleaned[k] == lead]
    if not hits:
        return None
    return [(hits[-1], carrier[1])] + list(segs[run:])


def _item_opener(cleaned: list[str], seg: tuple[int, int]) -> int | None:
    """First-item start in the carrier's tail: nearest determiner/wh-word."""
    s, e = seg
    for k in range(e, max(s - 1, e - ITEM1_BACKSCAN), -1):
        if cleaned[k] in _OPENERS:
            return k
    return None


def _map_candidate(*args: object, **kwargs: object) -> None:
    """Retired local-template selection; use the upstream catalog."""
    raise ValueError("Legacy list templates are retired; select the HyperFrames catalog")


def _long_list_candidate(*args: object, **kwargs: object) -> None:
    """Retired local-template selection; use the upstream catalog."""
    raise ValueError("Legacy list templates are retired; select the HyperFrames catalog")


def phrase(words: list[dict], i: int, j: int, cap: int) -> str:
    """Raw text of [i, j], trailing punctuation trimmed; cap words (0 = none)."""
    toks = [_word_text(words[k]) for k in range(i, j + 1)]
    if cap and len(toks) > cap:
        toks = toks[:cap] + ["…"]
    return " ".join(toks).strip().rstrip(string.punctuation + " ")


def _node_text(words: list[dict], i: int, j: int) -> str:
    """Node display text: leading a/an/the stripped, capped for the canvas."""
    if j > i and _clean(_word_text(words[i])) in _STRIP_DETERMINERS:
        i += 1
    return phrase(words, i, j, NODE_MAX_WORDS)
