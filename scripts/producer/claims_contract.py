#!/usr/bin/env python3
"""claims_contract — the pre-render TRUTH gate on claim-bearing card copy.

Implements MODULE_STUDY.md §1.2 #11 at the CHEAP point (§5.6, item 6): a
false number on a card is visible in the PLAN as text beside a transcript
window, so it is caught there instead of after paying for a full render.
Mirrors ``hook_contract.py``'s shape — content-derived obligations, a pure
check + a CLI run in the SKILL step-4 convergence loop as a MANDATORY
pre-render gate.

THE SPLIT (no regex for semantics): this module does ONLY the deterministic
half — every NUMERIC token in a card's copy must appear in the transcript
within the card's window (arithmetic string/number match: digits, $/%/x
edges, K/M/B suffix scales, spelled cardinals composed by lookup — never
regex-semantics). Whether the copy PARAPHRASES the claim faithfully, and
whether an ``evidence`` receipt matches its SOURCE, is the BRAIN's step-4
verification (SKILL step 4b "Copy/claims"). ``evidence*`` and ``icon*`` spec
slots are exempt here: a source receipt ("CLAIM SOURCE … JUL 09 2026") cites
the source, not the narration, and icon slots hold filenames.

Checked copy: every string in each ``graphicsTrack[].spec`` (nested lists/
objects included) plus ``titleCards[].text``. Source-declared top-level timing
controls are excluded through the template's shared content contract; they
are not painted copy. Numeric leaves of a dict that
declares a prefix/suffix affix slot (count-up's start/end) are checked as
their PAINTED string forms ("250%") — a hero number carried as a JSON number
must not slip past the gate just because it is not a string (review F2);
zero is exempt as the null counting origin. A card with no numeric copy
carries no deterministic obligation.

PHRASE GROUNDING (showpiece QC 2026-07-10, FAILURE_LEDGER.md LL-003): the
c0679 lower-third rendered "FREE — LINK IN DESCRIPTION" and the speaker never
says it in the cut — the numeric gate can't see word-only claims. So every
rendered sub-phrase (pipe/newline-split) of MORE THAN TWO WORDS must be
SPOKEN in the card's window: at least half its tokens (cleaned words or
matching numbers — pure membership arithmetic, no fuzzy matching) must
appear among the kept words, OR the whole normalized phrase must sit in the
declared ``STRUCTURAL_LABELS`` allowlist (neutral chrome — eyebrows/labels a
comp renders as structure, not claims). LESSON-001: never author CTA/card
copy the speaker does not say. The half floor keeps faithful paraphrase
legal ("can ... even be better" grounds "Even the prompts could be better");
faithfulness itself stays the brain's step-4b call.

BEAT COVERAGE (operator review 2026-07-10, FAILURE_LEDGER.md LL-009): a
graphic must EARN its beat — advance the argument or emphasize the words
being spoken at its window. The deterministic FLOOR here: a card whose copy
carries content tokens (cleaned tokens of ≥ ``COVERAGE_MIN_TOKEN_LEN`` chars
or numeric claims, structural chrome exempt) must share at least
``COVERAGE_MIN_TOKENS`` of them with the spoken window — a decorative card
whose copy has nothing to do with what is being said fails outright. NOTE
the floor's honest limit: the c0679 "RIGHT NOW" rail (titles spoken verbatim
in-window) PASSES it — verbatim-redundant restatement is a SEMANTIC defect
only LESSON-009 (the brain's step-4 read) can catch. The floor kills the
unrelated/decorative variant; the brain owns "does this move the
conversation forward".
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from planner import motion_triggers as mt  # noqa: E402
from graphics.template_content import is_timing_control  # noqa: E402
from graphics.template_contract import template_catalog  # noqa: E402

# A claim may be spoken slightly outside the card's hold — same proximity band
# as hook_contract.COVER_NEAR_S (a graphic covers a beat within 3s of it).
CLAIM_NEAR_S = 3.0
_SKIP_PREFIXES = ("icon", "evidence")   # filenames / source receipts, not copy
_EDGE_PUNCT = "\"'()[]{}.,;:!?"
_RATIO_CHARS = set("0123456789:/-.x×")  # "9:16", "24/7" — shape tokens

# ---- number vocabulary (data catalog — exempt from the line budget) -------- #
_SMALL_WORDS = {w: float(i) for i, w in enumerate((
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
    "sixteen", "seventeen", "eighteen", "nineteen"))}
_SMALL_WORDS.update({w: float(20 + 10 * i) for i, w in enumerate((
    "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty",
    "ninety"))})
_ORDINAL_WORDS = {w: float(i + 1) for i, w in enumerate((
    "first", "second", "third", "fourth", "fifth", "sixth", "seventh",
    "eighth", "ninth", "tenth"))}
_BIG_SCALES = {"thousand": 1e3, "million": 1e6, "billion": 1e9,
               "trillion": 1e12}
_SUFFIX_SCALES = {"k": 1e3, "m": 1e6, "b": 1e9, "t": 1e12}
_ORDINAL_SUFFIXES = ("st", "nd", "rd", "th")


def token_value(tok: str) -> float | None:
    """Arithmetic value of one token ('$300+', '92%', '450M', '1,000', '3rd',
    '10x', '4.5') — None when it is not a single parseable number."""
    t = str(tok).strip().strip(_EDGE_PUNCT).lstrip("$€£").rstrip("%+x×X")
    low, scale = t.lower(), 1.0
    if low.endswith(_ORDINAL_SUFFIXES) and low[:-2].isdigit():
        t = t[:-2]
    elif low[-1:] in _SUFFIX_SCALES and any(c.isdigit() for c in low[:-1]):
        scale, t = _SUFFIX_SCALES[low[-1]], t[:-1]
    try:
        return float(t.replace(",", "")) * scale
    except ValueError:
        return None


def claim_tokens(text: str) -> list[str]:
    """The numeric COPY tokens a card owes the transcript: tokens that parse
    arithmetically, plus digit/separator shape tokens ('9:16', '24/7').
    Digit-bearing NAMES ('GPT-5.6', '#c6f542', 'v2') are entities, not
    claims — the brain's semantic pass owns those."""
    out = []
    for tok in " ".join(_units(text)).split():
        if not any(c.isdigit() for c in tok):
            continue
        bare = tok.strip(_EDGE_PUNCT)
        if token_value(tok) is not None or (
                bare and set(bare) <= _RATIO_CHARS):
            out.append(tok)
    return out


def _run_values(tokens: list[str]) -> set[float]:
    """All prefix values of one spoken number run ('four hundred fifty' →
    {4, 400, 450}; '450 million' → {450, 450000000}). Pure arithmetic."""
    vals: set[float] = set()
    total = cur = 0.0
    seen = False
    for tok in tokens:
        v = token_value(tok) if any(c.isdigit() for c in tok) else None
        if v is not None:
            cur += v
        elif tok in _SMALL_WORDS:
            cur += _SMALL_WORDS[tok]
        elif tok == "hundred":
            cur = (cur if cur else 1.0) * 100.0
        elif tok in _BIG_SCALES:
            total, cur = total + (cur if cur else 1.0) * _BIG_SCALES[tok], 0.0
        else:
            continue                     # percent/dollars/etc. add no value
        seen = True
        vals.add(total + cur)
    return vals if seen else set()


def window_values(words: list[dict]) -> tuple[set[float], set[str]]:
    """(numeric values, cleaned raw tokens) spoken in a kept-word window.

    Values come from three arithmetic readings: each digit token on its own,
    each ordinal word ('first' → 1), and every composed number RUN surfaced by
    the shared trigger vocabulary (``motion_triggers.detect_numbers`` — the
    same detector the graphics lanes read, so gate and planner can't drift).
    """
    cleaned = [mt._clean(mt._word_text(w)) for w in words]
    vals: set[float] = set()
    raws: set[str] = set(c for c in cleaned if c)
    for w, c in zip(words, cleaned):
        raw = mt._word_text(w)
        if any(ch.isdigit() for ch in raw):
            v = token_value(raw)
            if v is not None:
                vals.add(v)
        if c in _ORDINAL_WORDS:
            vals.add(_ORDINAL_WORDS[c])
    for cand in mt.detect_numbers(words, cleaned):
        idx = cand.get("wordIndices") or []
        vals |= _run_values([cleaned[k] for k in idx])
    return vals, raws


_AFFIX_KEYS = ("prefix", "suffix")


def _painted_number(value: Any) -> str | None:
    """The string a comp PAINTS for one numeric leaf; None when it is not a
    painted claim (bools, non-numbers, and zero — the null origin a counter
    departs from, not authored copy)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value == 0:
        return None
    return str(int(value)) if float(value) == int(value) else f"{value:g}"


def _affixed_numbers(node: dict, path: str) -> list[tuple[str, str]]:
    """(path, painted) rows for numeric leaves of an AFFIX-carrying dict.

    A spec that declares a prefix/suffix slot (count-up's start/end) renders
    its numbers AS COPY through that lockup — so the hero number a JSON
    number carries must face the truth gate as the exact painted string
    ("250%"), review F2. Dicts without affix slots keep numbers exempt
    (timing/geometry knobs are not copy).
    """
    if not any(isinstance(node.get(key), str) for key in _AFFIX_KEYS):
        return []
    prefix = node.get("prefix") if isinstance(node.get("prefix"), str) else ""
    suffix = node.get("suffix") if isinstance(node.get("suffix"), str) else ""
    return [(f"{path}.{key}", f"{prefix}{painted}{suffix}")
            for key, value in node.items()
            for painted in (_painted_number(value),) if painted is not None]


def _spec_strings(node: Any, path: str = "spec") -> list[tuple[str, str]]:
    """(path, text) for every string in a spec tree, skipping exempt slots;
    numeric leaves painted through an affix lockup ride along as their
    painted string forms."""
    if isinstance(node, str):
        return [(path, node)]
    if isinstance(node, dict):
        return [p for k, v in node.items()
                if not str(k).lower().startswith(_SKIP_PREFIXES)
                for p in _spec_strings(v, f"{path}.{k}")] \
            + _affixed_numbers(node, path)
    if isinstance(node, (list, tuple)):
        return [p for j, v in enumerate(node)
                for p in _spec_strings(v, f"{path}[{j}]")]
    return []


def _matches(tok: str, vals: set[float], raws: set[str]) -> bool:
    """One copy token against the spoken window: value match, else string."""
    v = token_value(tok)
    if v is not None:
        return any(abs(v - x) <= 1e-6 * max(1.0, abs(v)) for x in vals)
    return mt._clean(tok) in raws


# Declared structural-chrome allowlist (LL-003): normalized phrases a comp
# renders as STRUCTURE (eyebrows / receipt labels / list headers), not spoken
# claims. Extend ONLY when a comp introduces new neutral chrome — never to
# whitelist a CTA or a claim. Data catalog — exempt from the line budget.
STRUCTURAL_LABELS = frozenset({
    "who this is for",       # glass-rail audience eyebrow (c0679, QC-clean)
    "claim source",          # receipt-line label (module/statement ribbon)
    "the plan",              # agenda-slide default eyebrow
})


def _units(text: str) -> list[str]:
    """Rendered sub-units of one string (pipe/newline are the comps'
    multi-value separators, so each unit is judged on its own)."""
    return [p.strip() for chunk in str(text).split("|")
            for p in chunk.splitlines() if p.strip()]


def _phrases(text: str) -> list[str]:
    """>2-word sub-phrases of one rendered string."""
    return [p for p in _units(text) if len(p.split()) > 2]


# LL-009 coverage floor: how many of a card's content tokens must be spoken
# in its window, and what counts as a content token (cleaned length floor —
# short glue words carry no beat; numeric claim tokens always count).
COVERAGE_MIN_TOKENS = 2
COVERAGE_MIN_TOKEN_LEN = 4


def _is_structural(unit: str) -> bool:
    """The unit's normalized form sits in the structural-chrome allowlist."""
    return " ".join(mt._clean(t) for t in unit.split() if mt._clean(t)) \
        in STRUCTURAL_LABELS


def _content_tokens(texts: list[tuple[str, str]]) -> set[str]:
    """Unique CLEANED content tokens across a card's copy (LL-009).

    Structural-chrome units contribute nothing (and owe nothing); a content
    token is a cleaned token of ≥ COVERAGE_MIN_TOKEN_LEN chars or a numeric
    claim token — pure membership arithmetic, no semantics.
    """
    out: set[str] = set()
    for _path, text in texts:
        for unit in _units(text):
            if _is_structural(unit):
                continue
            for tok in unit.split():
                c = mt._clean(tok)
                if c and (len(c) >= COVERAGE_MIN_TOKEN_LEN
                          or token_value(tok) is not None):
                    out.add(c)
    return out


def _check_coverage(tag: str, tokens: set[str], ctx: tuple, rep: Any) -> None:
    """LL-009 — the card's content tokens must touch the spoken window."""
    vals, raws, lo, hi = ctx
    shared = sum(1 for c in tokens
                 if c in raws or (token_value(c) is not None
                                  and _matches(c, vals, raws)))
    need = min(COVERAGE_MIN_TOKENS, len(tokens))
    if shared >= need:
        return
    rep.error(f"{tag}: card copy shares {shared} content token(s) with the "
              f"spoken window [{lo:.1f},{hi:.1f}]s (needs {need}) — the "
              "graphic does not touch what is being said (LL-009 / "
              "LESSON-009: a graphic must advance the argument or emphasize "
              "the spoken words; decorative cards are worse than clean face)")


def _phrase_grounded(phrase: str, vals: set[float], raws: set[str]) -> bool:
    """At least half the phrase's cleanable tokens are spoken in-window."""
    if " ".join(mt._clean(t) for t in phrase.split() if mt._clean(t)) \
            in STRUCTURAL_LABELS:
        return True
    toks = [t for t in phrase.split() if mt._clean(t)]
    if not toks:
        return True
    spoken = sum(1 for t in toks if _matches(t, vals, raws))
    return spoken * 2 >= len(toks)


def _check_card(tag: str, texts: list[tuple[str, str]],
                ctx: tuple, rep: Any) -> None:
    """Numeric tokens, >2-word phrases AND the LL-009 coverage floor."""
    words_out, s, e = ctx
    owed = [(path, tok) for path, text in texts for tok in claim_tokens(text)]
    phrases = [(path, p) for path, text in texts for p in _phrases(text)]
    content = _content_tokens(texts)
    if not owed and not phrases and not content:
        return                                   # nothing owed
    lo, hi = s - CLAIM_NEAR_S, e + CLAIM_NEAR_S
    win = [w for w in words_out if lo <= float(w.get("start", 1e18)) <= hi]
    vals, raws = window_values(win)
    if content:
        _check_coverage(tag, content, (vals, raws, lo, hi), rep)
    for path, tok in owed:
        if _matches(tok, vals, raws):
            continue
        rep.error(f"{tag}: {path} numeric copy {tok!r} is not spoken in the "
                  f"card's window [{lo:.1f},{hi:.1f}]s — card numbers must "
                  "match the kept words (fix the copy or move the card; a "
                  "faithful PARAPHRASE is the brain's step-4 call, "
                  "MODULE_STUDY §5.6)")
    for path, phrase in phrases:
        if _phrase_grounded(phrase, vals, raws):
            continue
        rep.error(f"{tag}: {path} rendered phrase {phrase!r} is not spoken in "
                  f"the card's window [{lo:.1f},{hi:.1f}]s — LESSON-001: never "
                  "author CTA/card copy the speaker does not say (fix the "
                  "copy, move/extend the cut to include the spoken line, or — "
                  "for genuine structural chrome only — add it to "
                  "claims_contract.STRUCTURAL_LABELS)")


def _claim_spec(entry: dict, catalog: dict) -> dict:
    """Exclude only source-declared top-level timing controls from claims."""
    spec = entry.get("spec") or {}
    declared = catalog.get(str(entry.get("kind", "")), {}).get("variables", {})
    values = {key: value for key, value in spec.items()
              if not is_timing_control(key, declared.get(key, {}))}
    if entry.get("kind") == "chart-story" and isinstance(values.get("data"), str):
        values["data"] = [token.strip() for token in values["data"].split(",")]
    return values


def check_claims_contract(plan: dict, words_out: list[dict], rep: Any) -> None:
    """Fail (``rep.error``) every claim-bearing card whose numeric copy does
    not appear in the transcript within its window. Pure; plan untouched."""
    graphics = plan.get("graphicsTrack") or []
    catalog = template_catalog() if graphics else {}
    for i, g in enumerate(graphics):
        s = float(g.get("outStart", 0.0))
        e = float(g.get("outEnd", s))
        _check_card(f"graphicsTrack[{i}]", _spec_strings(_claim_spec(g, catalog)),
                    (words_out, s, e), rep)
    for i, c in enumerate(plan.get("titleCards") or []):
        s = float(c.get("outStart", 0.0))
        e = float(c.get("outEnd", s))
        _check_card(f"titleCards[{i}]", [("text", str(c.get("text", "")))],
                    (words_out, s, e), rep)


def _cli() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("plan"); ap.add_argument("transcripts_dir"); ap.add_argument("manifest")
    a = ap.parse_args()
    from graphics_planner import output_words  # local: heavy import
    import plan_lint
    plan = json.load(open(a.plan)); manifest = json.load(open(a.manifest))
    words = output_words(plan, a.transcripts_dir, manifest)
    rep = plan_lint.Report()
    check_claims_contract(plan, words, rep)
    print(json.dumps({"ok": not rep.errors, "errors": rep.errors,
                      "warnings": rep.warnings}, indent=2))
    return 0 if not rep.errors else 1


if __name__ == "__main__":
    raise SystemExit(_cli())
