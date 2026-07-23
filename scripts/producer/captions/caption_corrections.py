#!/usr/bin/env python3
"""caption_corrections — fix ASR mishears before captions (MG-2 corrections).

Deepgram mishears a proper noun and, left alone, it becomes a burned-in caption
misspelling ("Hermosibot" for "Hormozi bot"). This module applies a plan's
``captions.corrections`` map — ``{heard: correct}`` — to the OUTPUT-time word list
BEFORE ``captions.build_ass`` runs (see docs/producer/PRODUCER_PLAN.md §4.5 "Caption
corrections"). It fixes TRANSCRIPTION errors ONLY; it never paraphrases or
changes what was said, and it never reorders words in time.

Matching contract:
- **Case-insensitive, whole-word.** The key matches on a word's CORE (its text
  with surrounding punctuation stripped), so ``"Hermosibot"`` matches the word
  ``"Hermosibot."`` and the trailing period is re-attached to the fix. It never
  matches a substring inside a larger word.
- **Multi-word keys** (``"Hermosia bot"``) match CONSECUTIVE words. Longer keys
  are tried first so a phrase key wins over a single-word key at the same spot.
- **Time-span split.** The corrected value's tokens split the matched span
  proportionally by character length (mirrors ``captions._split_oversized``), so
  a 1→2 word fix ("Hermosibot" → "Hormozi bot") keeps karaoke timing monotonic.

Validation is lenient by design: a key that matches nothing is a WARNING
(``unmatched_keys``), not an error — a plan may carry corrections for words that
a given cut happened not to include.

CLI: caption_corrections.py <words.json> <corrections.json> <out_words.json>
  words.json = a flat ``[{word,start,end,...}]`` list OR a transcript dict with a
  ``"transcript"`` list of utterances (auto-flattened); corrections.json =
  ``{"heard": "correct", ...}``.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass

# Split a token into (leading punct, core, trailing punct). The core is the
# word stripped of surrounding non-word chars; internal apostrophes/hyphens
# ("don't", "twenty-five") stay in the core because they are followed by a
# word char, so the trailing \W* cannot claim them.
_AFFIX_RE = re.compile(r"^(\W*)(.*?)(\W*)$")


@dataclass
class _Spec:
    """One prepared correction: matched key tokens → verbatim replacement."""

    key: str            # original "heard" string, as given (for the log)
    tokens: list[str]   # per-word lowercased cores to match consecutively
    corrected: str      # replacement value, used verbatim (case preserved)


def _affixes(text: str) -> tuple[str, str, str]:
    """Return (leading_punct, core, trailing_punct) for a token."""
    match = _AFFIX_RE.match(str(text))
    if not match:
        return "", str(text), ""
    return match.group(1), match.group(2), match.group(3)


def _core_lower(text: str) -> str:
    """Lowercased core of a token (surrounding punctuation stripped)."""
    return _affixes(text)[1].lower()


def _prepare(corrections: dict) -> list[_Spec]:
    """Build match specs from the corrections map, longest-key-first.

    Degenerate entries (empty key core or empty replacement) are dropped — a
    correction can fix a mishear but never delete a word.
    """
    specs: list[_Spec] = []
    for key, value in corrections.items():
        tokens = [t for t in (_core_lower(part) for part in str(key).split()) if t]
        corrected = str(value).strip()
        if not tokens or not corrected.split():
            continue
        specs.append(_Spec(key=str(key), tokens=tokens, corrected=corrected))
    specs.sort(key=lambda s: len(s.tokens), reverse=True)
    return specs


def _match_at(words: list[dict], i: int, specs: list[_Spec]) -> _Spec | None:
    """First spec whose tokens match the words starting at index ``i``."""
    for spec in specs:
        k = len(spec.tokens)
        if i + k > len(words):
            continue
        if all(_core_lower(words[i + j]["word"]) == spec.tokens[j] for j in range(k)):
            return spec
    return None


def _split_span(start: float, end: float, tokens: list[str]) -> list[tuple[str, float, float]]:
    """Split ``[start, end]`` across ``tokens`` proportionally by char length.

    The last token's end is pinned to ``end`` exactly so no rounding drift
    accumulates; timing stays non-decreasing (``captions._split_oversized``
    pattern). A degenerate span (``end <= start``) collapses every token onto
    ``start`` rather than going backwards.
    """
    end = max(end, start)
    total_chars = sum(len(t) for t in tokens) or len(tokens)
    per_char = (end - start) / total_chars if total_chars else 0.0
    out: list[tuple[str, float, float]] = []
    cursor = start
    for idx, token in enumerate(tokens):
        piece_end = end if idx == len(tokens) - 1 else cursor + per_char * len(token)
        out.append((token, round(cursor, 4), round(piece_end, 4)))
        cursor = piece_end
    return out


def _replace(matched: list[dict], spec: _Spec) -> list[dict]:
    """Build replacement word dicts for a matched span (affixes preserved)."""
    first, last = matched[0], matched[-1]
    lead = _affixes(str(first["word"]))[0]
    trail = _affixes(str(last["word"]))[2]
    pieces = _split_span(float(first["start"]), float(last["end"]), spec.corrected.split())
    out: list[dict] = []
    for idx, (token, start, end) in enumerate(pieces):
        text = token
        if idx == 0:
            text = lead + text
        if idx == len(pieces) - 1:
            text = text + trail
        entry = dict(first)                       # preserve extra keys (confidence)
        entry.update({"word": text, "start": start, "end": end})
        out.append(entry)
    return out


def apply_corrections(words: list[dict], corrections: dict) -> tuple[list[dict], list[dict]]:
    """Apply ``corrections`` to output-time ``words``.

    Returns ``(new_words, log)`` where ``log`` is a list of
    ``{"at", "heard", "corrected"}`` — one entry per applied correction, ``at``
    being the start timestamp of the first matched word. Word order and timing
    monotonicity are preserved. Use ``unmatched_keys`` to surface keys that
    matched nothing (a warning, not an error).
    """
    specs = _prepare(corrections)
    out: list[dict] = []
    log: list[dict] = []
    i, n = 0, len(words)
    while i < n:
        spec = _match_at(words, i, specs)
        if spec is None:
            out.append(words[i])
            i += 1
            continue
        matched = words[i:i + len(spec.tokens)]
        out.extend(_replace(matched, spec))
        log.append({"at": round(float(matched[0]["start"]), 3),
                    "heard": spec.key, "corrected": spec.corrected})
        i += len(spec.tokens)
    return out, log


def unmatched_keys(corrections: dict, log: list[dict]) -> list[str]:
    """Correction keys that matched no words in this run (validation warnings)."""
    applied = {entry["heard"] for entry in log}
    return [key for key in corrections if key not in applied]


def kept_words(ctx, tmap, emit) -> list:
    """Gather every source's words, remapped to output time, sorted.

    ``ctx`` is the renderer's duck-typed RenderCtx (``manifest``/``out_dir``);
    ``emit`` its NDJSON status emitter.
    """
    from compile_timeline import remap_words
    manifest_dir = os.path.dirname(os.path.abspath(
        ctx.manifest.get("_path", os.path.join(ctx.out_dir, "x"))))
    words: list = []
    for src in ctx.manifest.get("sources", []):
        rel = src.get("transcriptPath")
        if not rel:
            emit(status="captions_source_skipped", id=src["id"],
                 reason="no transcript")
            continue
        path = rel if os.path.isabs(rel) else os.path.join(manifest_dir, rel)
        with open(path) as f:
            entries = json.load(f).get("transcript", [])
        flat = [w for e in entries for w in e.get("words", [])]
        words.extend(remap_words(flat, src["id"], tmap))
    return sorted(words, key=lambda w: w["start"])


def corrected_caption_words(ctx, tmap, emit) -> list:
    """Kept words after the one grounded caption-correction contract."""
    from producer_config import CAPTION_AUTO_CORRECTIONS
    words = kept_words(ctx, tmap, emit)
    corrections = dict(CAPTION_AUTO_CORRECTIONS)
    corrections.update((ctx.plan.get("captions") or {}).get("corrections") or {})
    if not corrections:
        return words
    words, corr_log = apply_corrections(words, corrections)
    emit(status="captions_corrected", applied=len(corr_log),
         unmatched=unmatched_keys(corrections, corr_log))
    return words


def flatten_words(data: object) -> list[dict]:
    """Accept a flat word list or a transcript dict → flat output-time words."""
    if isinstance(data, dict) and isinstance(data.get("transcript"), list):
        words: list[dict] = []
        for utterance in data["transcript"]:
            words.extend(utterance.get("words", []))
        return words
    if isinstance(data, list):
        return data
    raise ValueError("words.json must be a list or a transcript dict with 'transcript'")


def main() -> None:
    args = sys.argv[1:]
    if len(args) != 3:
        print(json.dumps({"error": "Usage: caption_corrections.py <words.json> "
                                   "<corrections.json> <out_words.json>"}))
        sys.exit(1)
    try:
        with open(args[0]) as fh:
            words = flatten_words(json.load(fh))
        with open(args[1]) as fh:
            corrections = json.load(fh)
        new_words, log = apply_corrections(words, corrections)
        with open(args[2], "w") as fh:
            json.dump(new_words, fh, indent=2)
    except (OSError, json.JSONDecodeError, ValueError, KeyError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)
    print(json.dumps({"status": "done", "in_words": len(words),
                      "out_words": len(new_words), "applied": len(log),
                      "log": log, "unmatched": unmatched_keys(corrections, log),
                      "out": args[2]}, indent=2))


if __name__ == "__main__":
    main()
