#!/usr/bin/env python3
"""motion_triggers — deterministic candidate detector for motion graphics.

A high-RECALL, zero-judgment pass over a word-timed transcript: it finds every
spot where the WORDS carry structure the ear alone holds poorly (numbers,
enumerations, named entities, contrasts, sequences, thesis lines) and emits them
as candidates. The BRAIN (a skill) decides which candidates actually earn a
graphic — this module never judges taste, it only surfaces options. See
docs/producer/PRODUCER_MOTION_GRAPHICS_PLAN.md §1 (trigger taxonomy) and §4 (skills-vs-
logic split: this is the LOGIC side).

Operates on whatever word list the caller hands it — SOURCE-time words straight
off the transcript, or OUTPUT-time words already remapped by compile_timeline.
``wordIndices`` are positions in THAT list; timing is derived downstream via the
timeline map, never invented here.

Pure stdlib + regex (no numpy/cv2). CLI:
    motion_triggers.py <words.json> [--entities brands.txt] [--gap SECONDS]
where <words.json> is a raw word list, a ``{"words": [...]}`` object, or a full
Deepgram-style ``{"transcript": [{"words": [...]}, ...]}`` (auto-flattened).
Prints the candidate JSON array to stdout.
"""

from __future__ import annotations

import json
import string
import sys
from typing import Iterable, Optional

# =========================================================================== #
# DATA (catalogs / lookup sets) — O(1) membership; exempt from the line limit.
# =========================================================================== #
_ONES = {"zero", "one", "two", "three", "four", "five", "six", "seven",
         "eight", "nine"}
_TEENS = {"ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
          "sixteen", "seventeen", "eighteen", "nineteen"}
_TENS = {"twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty",
         "ninety"}
_SCALES = {"hundred", "thousand", "million", "billion", "trillion"}
# Spelled cardinals that read as a NUMBER graphic ("ten years", "one zero one").
NUMBER_WORDS = _ONES | _TEENS | _TENS | _SCALES

# Ordinals that read as list/sequence position, not as a count.
SEQUENCE_STRONG = {"first", "firstly", "second", "secondly", "third", "thirdly",
                   "fourth", "fifth", "finally", "lastly", "step", "steps"}
SEQUENCE_WEAK = {"then", "next"}
# Tokens that promote an ordinal to a real list item ("the first THING").
_LIST_NOUNS = {"thing", "things", "step", "steps", "reason", "reasons",
               "way", "ways", "point", "part"}

# Contrast markers. Two-word phrases matched as adjacent cleaned tokens.
CONTRAST_PHRASES = (("instead", "of"), ("rather", "than"),
                    ("as", "opposed"), ("not", "just"), ("as", "against"))
CONTRAST_WORDS = {"versus", "vs"}

# Modifiers allowed between a count and its noun ("three MORE days").
_ENUM_MODIFIERS = {"more", "other", "different", "new", "big", "biggest",
                   "small", "main", "key", "whole", "same", "few", "extra",
                   "single", "total", "separate"}

# Function words that can never be the NOUN a count governs — reject
# 'number + <function word>' enumerations ('50% for', '50 off', '$12k and').
_ENUM_NOUN_STOP = {"and", "or", "but", "the", "a", "an", "of", "to", "for",
                   "with", "in", "on", "at", "by", "is", "was", "are", "were",
                   "be", "been", "that", "this", "these", "those", "you", "we",
                   "it", "they", "he", "she", "so", "as", "if", "off", "up",
                   "out", "then", "there", "here", "not", "no", "yes", "just",
                   "more", "like", "from", "into", "than"}

# Enumeration LEAD-INS with an implicit count ("some of the things...", the
# spoken list intro). Matched as adjacent cleaned-token phrases.
ENUM_CUE_PHRASES = (("some", "of", "the", "things"), ("on", "the", "docket"),
                    ("a", "couple", "of"), ("a", "few"), ("a", "bunch", "of"),
                    ("a", "number", "of"), ("a", "list", "of"),
                    ("the", "following"), ("couple", "of", "things"))

# Title-case FUNCTION words that must never read as a named entity — pronouns,
# contractions, discourse markers. Compared against the lowercased bare token.
ENTITY_STOP = {"i", "i'm", "i've", "i'd", "i'll", "my", "this", "that",
               "these", "those", "you", "we", "they", "he", "she", "it",
               "okay", "alright", "well", "like", "so", "and", "but", "yeah",
               "yo", "wow", "hey", "no", "yes", "oh", "sure", "right", "great",
               "good", "sorry", "man", "now", "then", "here", "there", "also",
               "let", "let's", "gotcha", "guys", "k", "um", "uh"}

# Thesis lead-ins: the sentence after one of these is the line the clip exists
# for. Matched as adjacent cleaned-token phrases.
THESIS_CUES = (("the", "truth", "is"), ("here", "is", "the", "thing"),
               ("the", "thing", "is"), ("the", "point", "is"),
               ("the", "reason", "is"), ("the", "bottom", "line"),
               ("the", "fact", "is"), ("the", "reality", "is"),
               ("what", "i", "realized"), ("the", "key", "is"),
               ("what", "matters", "is"), ("the", "real", "reason"))
# Absolute / superlative words that flag a probable thesis (weaker signal).
ABSOLUTE_WORDS = {"nobody", "everybody", "everyone", "anybody", "never",
                  "always", "only", "hate", "love", "best", "worst", "most",
                  "biggest", "greatest", "essential", "impossible", "truth",
                  "completely", "literally", "actually", "misunderstand"}
# Lead-ins that open a rhetorical QUESTION. A short pointed question ("where are
# your priorities?") is a thesis-grade beat — the stressed line a punch-in/bracket
# lands on — but it carries no cue phrase or absolute word, so the cue/absolute
# passes miss it. The question pass anchors on a "?" and walks back to the clause
# opener: a wh-INTERROGATIVE opens the clause (preferred), else the earliest
# AUXILIARY (a yes/no question, "are you posting?"). Matched lowercased.
WH_LEADS = {"where", "what", "why", "how", "who", "when", "which", "whose"}
AUX_LEADS = {"is", "are", "am", "was", "were", "do", "does", "did", "can",
             "could", "should", "would", "will", "have", "has", "had",
             "aren't", "isn't", "don't", "doesn't", "didn't", "won't",
             "wouldn't", "couldn't", "shouldn't", "can't"}
QUESTION_LEADS = WH_LEADS | AUX_LEADS
_QUESTION_MAX_WORDS = 9       # a thesis-grade question is short + pointed

# Topic-boundary cues — a chapter/section shift surfaces as an UTTERANCE START
# carrying a discourse marker (operator's set, 2026-07-05). Phrases are adjacent
# cleaned tokens; singles are 1-tuples; the LONGEST match at a position wins.
# See PRODUCER_MOTION_GRAPHICS_PLAN.md §1 (topic boundaries → transition
# stingers) and the MG-3 pointer in §5 (extend this module, don't fork it).
TOPIC_MARKERS = (("okay", "so"), ("so", "now"), ("next", "up"),
                 ("moving", "on"), ("all", "right"),   # spelled 'alright'
                 ("alright",), ("let's",))
# Position words that open an enumerated section ("the LAST thing", "the SECOND
# thing"): the sequence ordinals plus 'last'/'next', governing a list noun.
SECTION_ORDINALS = SEQUENCE_STRONG | {"last", "next"}
# Default pause (s) that promotes an utterance start to a boundary signal. A
# separate detector default from the sentence-level cues — tunable per run.
TOPIC_GAP_S = 1.5
# Tokens into an utterance to scan for an enumerated-section lead-in.
_SECTION_SCAN = 5

_ENDERS = (".", "?", "!")
_STRIP = string.punctuation  # leading/trailing punctuation to peel for matching
_THESIS_SPAN_CAP = 12        # max tokens a thesis span may cover


# =========================================================================== #
# Token helpers (pure).
# =========================================================================== #
def _word_text(w: dict) -> str:
    """The raw surface token of a word entry ('word' or 'text' key)."""
    return str(w.get("word", w.get("text", "")))


def _bare(tok: str) -> str:
    """Strip leading/trailing punctuation, preserving case + internal marks."""
    return tok.strip(_STRIP)


def _clean(tok: str) -> str:
    """Lowercased, punctuation-stripped form used for word matching."""
    return _bare(tok).lower()


def _ends_sentence(tok: str) -> bool:
    """True if this token closes a sentence (ends in . ? ! after quotes)."""
    return tok.rstrip("\"')").endswith(_ENDERS)


def _has_digit(tok: str) -> bool:
    """True if the raw token contains any digit (12, $99, 4002, 50%)."""
    return any(c.isdigit() for c in tok)


def _is_titlecase(bare: str) -> bool:
    """True for a Title-case word (leading cap, not an all-caps acronym)."""
    return bool(bare) and bare[:1].isupper() and not bare.isupper() \
        and any(c.isalpha() for c in bare)


def _is_acronym(bare: str) -> bool:
    """True for an all-caps alphabetic acronym of length >= 2 (MCP, API, AI)."""
    return len(bare) >= 2 and bare.isalpha() and bare.isupper()


def _sentence_starts(words: list[dict]) -> list[bool]:
    """Per-word flag: is this token the first of its sentence?"""
    starts = [False] * len(words)
    prev_ended = True
    for i, w in enumerate(words):
        starts[i] = prev_ended
        prev_ended = _ends_sentence(_word_text(w))
    return starts


def _sentence_end(words: list[dict], i: int) -> int:
    """Index of the last token of the sentence containing token ``i``."""
    for j in range(i, len(words)):
        if _ends_sentence(_word_text(words[j])):
            return j
    return len(words) - 1


def _span_text(words: list[dict], i: int, j: int) -> str:
    """Whitespace-joined raw text of the inclusive span [i, j]."""
    return " ".join(_word_text(words[k]) for k in range(i, j + 1)).strip()


def _cand(kind: str, words: list[dict], span: tuple[int, int], conf: str) -> dict:
    """Build one candidate dict for the inclusive word span ``(i, j)``."""
    i, j = span
    return {"trigger": kind, "wordIndices": list(range(i, j + 1)),
            "text": _span_text(words, i, j), "confidence": conf}


# =========================================================================== #
# Detectors — each returns a list of candidates. High recall by design.
# =========================================================================== #
def detect_numbers(words: list[dict], cleaned: list[str]) -> list[dict]:
    """Digits, currency, percentages and spelled cardinals (merged runs)."""
    out: list[dict] = []
    i, n = 0, len(words)
    while i < n:
        raw = _word_text(words[i])
        if not (_has_digit(raw) or cleaned[i] in NUMBER_WORDS):
            i += 1
            continue
        j = i
        while j + 1 < n and (_has_digit(_word_text(words[j + 1]))
                             or cleaned[j + 1] in NUMBER_WORDS):
            j += 1
        if j + 1 < n and cleaned[j + 1] in {"percent", "dollars", "bucks"}:
            j += 1
        strong = any(_has_digit(_word_text(words[k])) or "%" in _word_text(words[k])
                     or "$" in _word_text(words[k])
                     or cleaned[k] in _SCALES for k in range(i, j + 1))
        out.append(_cand("number", words, (i, j), "high" if strong else "medium"))
        i = j + 1
    return out


def detect_enumerations(words: list[dict], cleaned: list[str],
                        starts: list[bool]) -> list[dict]:
    """A count immediately governing a noun ('two settings', 'ten years')."""
    out: list[dict] = []
    n = len(words)
    for i in range(n):
        is_num = _has_digit(_word_text(words[i])) or cleaned[i] in NUMBER_WORDS
        if not is_num or cleaned[i] in _SCALES:
            continue
        if _ends_sentence(_word_text(words[i])):     # count closes its clause
            continue
        j = i + 1
        steps = 0
        while j < n and cleaned[j] in _ENUM_MODIFIERS and steps < 2:
            j, steps = j + 1, steps + 1
        if j >= n or not cleaned[j].isalpha() or cleaned[j] in NUMBER_WORDS:
            continue
        if cleaned[j] in _ENUM_NOUN_STOP:            # not a real noun
            continue
        if starts[j] or _ends_sentence(_word_text(words[j - 1])):
            continue                                 # noun is in the next clause
        conf = "medium" if cleaned[i] in {"one", "a"} else "high"
        out.append(_cand("enumeration", words, (i, j), conf))
    return out


def detect_enum_cues(words: list[dict], cleaned: list[str]) -> list[dict]:
    """Spoken list intros with an implicit count ('some of the things...')."""
    out: list[dict] = []
    for phrase in ENUM_CUE_PHRASES:
        for i in _phrase_hits(cleaned, list(phrase)):
            out.append(_cand("enumeration", words, (i, i + len(phrase) - 1),
                             "medium"))
    return out


def _merge_entity(words: list[dict], starts: list[bool], i: int) -> int:
    """Extend an entity run from ``i`` over adjacent title/acronym tokens.

    Stops at a comma (a ``Higgs Field's, AI`` run is two entities, not one).
    """
    j = i
    while j + 1 < len(words) and not starts[j + 1]:
        if _word_text(words[j]).rstrip().endswith(","):
            break
        nxt = _bare(_word_text(words[j + 1]))
        if (_is_titlecase(nxt) or _is_acronym(nxt)) and nxt.lower() not in ENTITY_STOP:
            j += 1
        else:
            break
    return j


def detect_entities(words: list[dict], starts: list[bool],
                    brands: frozenset[str]) -> list[dict]:
    """Capitalized non-sentence-initial runs, acronyms, and known brands."""
    out = _detect_capitalized(words, starts)
    out.extend(_detect_brands(words, brands))
    return out


def _detect_capitalized(words: list[dict], starts: list[bool]) -> list[dict]:
    """Title-case runs (mid-sentence) and standalone acronyms."""
    out: list[dict] = []
    i, n = 0, len(words)
    while i < n:
        bare = _bare(_word_text(words[i]))
        if starts[i] or not bare or bare.lower() in ENTITY_STOP:
            i += 1
            continue
        if _is_titlecase(bare):
            j = _merge_entity(words, starts, i)
            out.append(_cand("entity", words, (i, j), "high"))
            i = j + 1
        elif _is_acronym(bare):
            out.append(_cand("entity", words, (i, i),
                             "medium" if len(bare) == 2 else "high"))
            i += 1
        else:
            i += 1
    return out


def _detect_brands(words: list[dict], brands: frozenset[str]) -> list[dict]:
    """Match multi-word brand phrases from the caller's entity list."""
    if not brands:
        return []
    cleaned = [_clean(_word_text(w)) for w in words]
    out: list[dict] = []
    for phrase in brands:
        toks = phrase.split()
        for i in _phrase_hits(cleaned, toks):
            out.append(_cand("entity", words, (i, i + len(toks) - 1), "high"))
    return out


def _phrase_hits(cleaned: list[str], toks: list[str]) -> Iterable[int]:
    """Yield every start index where ``toks`` matches ``cleaned`` in order."""
    n, m = len(cleaned), len(toks)
    if m == 0:
        return
    for i in range(n - m + 1):
        if cleaned[i:i + m] == toks:
            yield i


def detect_contrasts(words: list[dict], cleaned: list[str]) -> list[dict]:
    """'instead of', 'rather than', 'versus', 'not X but Y', 'X, not Y'."""
    out: list[dict] = []
    n = len(words)
    for i in range(n):
        for phrase in CONTRAST_PHRASES:
            if cleaned[i:i + len(phrase)] == list(phrase):
                end = min(i + len(phrase) + 1, n - 1)
                out.append(_cand("contrast", words, (i, end), "high"))
        if cleaned[i] in CONTRAST_WORDS:
            span = (max(0, i - 1), min(i + 1, n - 1))
            out.append(_cand("contrast", words, span, "high"))
        if cleaned[i] == "not":
            out.extend(_not_contrast(words, cleaned, i))
    return out


def _not_contrast(words: list[dict], cleaned: list[str], i: int) -> list[dict]:
    """'not ... but ...' (high) or comma-led 'X, not Y' (medium)."""
    for k in range(i + 1, min(i + 9, len(words))):
        if cleaned[k] == "but":
            return [_cand("contrast", words, (i, k), "high")]
    if i > 0 and _word_text(words[i - 1]).rstrip().endswith(","):
        return [_cand("contrast", words, (i - 1, min(i + 2, len(words) - 1)),
                     "medium")]
    return []


def detect_sequences(words: list[dict], cleaned: list[str]) -> list[dict]:
    """Ordinals ('first/second/finally'), process markers ('then', 'next')."""
    out: list[dict] = []
    n = len(words)
    for i in range(n):
        c = cleaned[i]
        if c in SEQUENCE_STRONG:
            nxt = cleaned[i + 1] if i + 1 < n else ""
            strong = c in {"finally", "lastly", "step", "steps"} \
                or nxt in _LIST_NOUNS
            out.append(_cand("sequence", words, (i, min(i + 1, n - 1)),
                             "high" if strong else "medium"))
        elif c in SEQUENCE_WEAK:
            out.append(_cand("sequence", words, (i, i), "medium"))
    return out


def detect_thesis(words: list[dict], cleaned: list[str]) -> list[dict]:
    """Cue-led lines (high), rhetorical questions (high), absolutes (medium)."""
    out: list[dict] = []
    n = len(words)
    seen_ends: set[int] = set()
    for i in range(n):
        for cue in THESIS_CUES:
            if cleaned[i:i + len(cue)] == list(cue):
                end = min(_sentence_end(words, i), i + _THESIS_SPAN_CAP)
                out.append(_cand("thesis", words, (i, end), "high"))
                seen_ends.add(_sentence_end(words, i))
    for lead, mark in _detect_questions(words, cleaned):
        if mark in seen_ends:
            continue
        seen_ends.add(mark)
        out.append(_cand("thesis", words, (lead, mark), "high"))
    for i in range(n):
        if cleaned[i] not in ABSOLUTE_WORDS:
            continue
        s_end = _sentence_end(words, i)
        if s_end in seen_ends:
            continue
        seen_ends.add(s_end)
        out.append(_cand("thesis", words, (i, min(s_end, i + _THESIS_SPAN_CAP)),
                         "medium"))
    return out


def _detect_questions(words: list[dict], cleaned: list[str]) -> list[tuple[int, int]]:
    """(lead, mark) spans of short rhetorical questions ending in '?'.

    Anchors on each '?' token and walks back up to ``_QUESTION_MAX_WORDS`` (never
    crossing a prior sentence ender) for the earliest interrogative/auxiliary lead
    — so a question whose clause the punctuation didn't split off ("...my team is
    | where are your priorities?") is still bounded to just the question.
    """
    out: list[tuple[int, int]] = []
    for j in range(len(words)):
        if not _word_text(words[j]).rstrip("\"')").endswith("?"):
            continue
        wh_lead, aux_lead = None, None
        for k in range(j, max(-1, j - _QUESTION_MAX_WORDS), -1):
            if k < j and _ends_sentence(_word_text(words[k])):
                break
            if cleaned[k] in WH_LEADS:
                wh_lead = k                      # earliest wh in the window
            elif cleaned[k] in AUX_LEADS:
                aux_lead = k                     # earliest aux (yes/no fallback)
        lead = wh_lead if wh_lead is not None else aux_lead
        if lead is not None:
            out.append((lead, j))
    return out


def _gap_before(words: list[dict]) -> list[float]:
    """Silence (s) before each word: ``word[i].start - word[i-1].end`` (>= 0).

    0.0 when timing is missing or non-numeric, so callers handing in untimed
    words simply see no gap signal rather than crashing.
    """
    gaps = [0.0] * len(words)
    for i in range(1, len(words)):
        try:
            gaps[i] = max(0.0, float(words[i]["start"]) - float(words[i - 1]["end"]))
        except (KeyError, TypeError, ValueError):
            gaps[i] = 0.0
    return gaps


def _marker_len(cleaned: list[str], i: int) -> int:
    """Length of the longest topic-marker phrase starting at ``i`` (0 = none)."""
    best = 0
    for phrase in TOPIC_MARKERS:
        if len(phrase) > best and cleaned[i:i + len(phrase)] == list(phrase):
            best = len(phrase)
    return best


def _section_end(cleaned: list[str], starts: list[bool], i: int) -> int:
    """End index of an enumerated-section lead-in opening at utterance start ``i``.

    Scans up to ``_SECTION_SCAN`` tokens (stopping at the next utterance) for a
    position ordinal directly governing a list noun ('the LAST thing') and
    returns the noun's index, or ``i - 1`` (empty) when there is none.
    """
    n = len(cleaned)
    for k in range(i, min(i + _SECTION_SCAN, n - 1)):
        if k > i and starts[k]:
            break
        if cleaned[k] in SECTION_ORDINALS and cleaned[k + 1] in _LIST_NOUNS:
            return k + 1
    return i - 1


def detect_topic_boundaries(words: list[dict], cleaned: list[str],
                            starts: list[bool],
                            gap_s: float = TOPIC_GAP_S) -> list[dict]:
    """Utterance starts that open a new topic/section — chapter-stinger hooks.

    Three independent signals at an utterance start each add confidence: a
    discourse marker, a long preceding pause (>= ``gap_s``), and an enumerated-
    section lead-in. A bare pause is the weakest evidence (much livestream
    silence is just working dead air), so gap-only fires 'low'; a lone lexical
    cue is 'medium'; a lexical cue corroborated by a second signal is 'high'.
    An utterance start is a sentence start OR any word a long pause precedes.
    """
    gaps = _gap_before(words)
    out: list[dict] = []
    for i in range(len(words)):
        long_gap = gaps[i] >= gap_s
        if not (starts[i] or long_gap):        # only utterance starts are boundaries
            continue
        mlen = _marker_len(cleaned, i)
        send = _section_end(cleaned, starts, i)
        has_marker, has_enum = mlen > 0, send >= i
        signals = has_marker + long_gap + has_enum
        if not signals:
            continue
        if signals >= 2:
            conf = "high"                       # a lexical cue + corroboration
        elif has_marker or has_enum:
            conf = "medium"                     # a lone marker/section lead-in
        else:
            conf = "low"                        # a bare pause — weakest evidence
        end = max(i + mlen - 1, send, i)
        out.append(_cand("topic-boundary", words, (i, end), conf))
    return out


def detect_topic_boundaries_from_words(words: list[dict],
                                       gap_s: float = TOPIC_GAP_S) -> list[dict]:
    """``detect_topic_boundaries`` on a raw word list (derives cleaned + starts).

    A convenience for callers that hold raw SOURCE-time words and want ONLY the
    boundary pass: the graphics planner detects boundaries on source time (where
    the inter-topic pauses are still intact) and maps them forward, while running
    the other detectors on output time — see
    ``graphics_planner._source_topic_boundaries``.
    """
    cleaned = [_clean(_word_text(w)) for w in words]
    starts = _sentence_starts(words)
    return detect_topic_boundaries(words, cleaned, starts, gap_s)


# =========================================================================== #
# Orchestration.
# =========================================================================== #
def detect_all(words: list[dict], brands: frozenset[str] = frozenset(),
               gap_s: float = TOPIC_GAP_S) -> list[dict]:
    """Run every detector, dedupe exact repeats, sort by first word index."""
    cleaned = [_clean(_word_text(w)) for w in words]
    starts = _sentence_starts(words)
    cands: list[dict] = []
    cands += detect_numbers(words, cleaned)
    cands += detect_enumerations(words, cleaned, starts)
    cands += detect_enum_cues(words, cleaned)
    cands += detect_entities(words, starts, brands)
    cands += detect_contrasts(words, cleaned)
    cands += detect_sequences(words, cleaned)
    cands += detect_thesis(words, cleaned)
    cands += detect_topic_boundaries(words, cleaned, starts, gap_s)
    return _dedupe(cands)


def _dedupe(cands: list[dict]) -> list[dict]:
    """Drop exact (trigger, span) duplicates; sort by span start then kind."""
    seen: set[tuple] = set()
    unique: list[dict] = []
    for c in cands:
        key = (c["trigger"], tuple(c["wordIndices"]))
        if key in seen:
            continue
        seen.add(key)
        unique.append(c)
    unique.sort(key=lambda c: (c["wordIndices"][0], c["trigger"]))
    return unique


# Momentum zones: a run of list items / counts / steps is where the pro
# accelerates (study P4). Clustering these triggers lets the planner pace a
# change PER ITEM across the whole run, not merely clear the baseline floor.
MOMENTUM_TRIGGERS = ("enumeration", "sequence", "number")
MOMENTUM_CLUSTER_GAP_S = 8.0   # items whose spans are within this join one run
MOMENTUM_MIN_ITEMS = 2         # a lone number / step is not a momentum run


def momentum_zones(candidates: list[dict], words: list[dict],
                   gap_s: float = MOMENTUM_CLUSTER_GAP_S) -> list[dict]:
    """Cluster enumeration / sequence / number candidates into momentum zones.

    A momentum zone is a high-energy content run (a numbered list, a sequence of
    steps, a burst of counts) where the pro accelerates the visual rhythm. The
    numeric rate target is NOT yet measured (see docs/studies/PACING_RHYTHM_STUDY.md
    caveat), so a zone is guidance to pace a change per item — not a lint floor.

    Args:
        candidates: ``detect_all`` output (each carries ``trigger`` +
            ``wordIndices``).
        words: the OUTPUT-time words those indices point into (``start`` / ``end``).
        gap_s: items whose output-time spans are within this gap join one run.

    Returns:
        Zones ``{outStart, outEnd, items, triggers}`` in output order, each with
        at least ``MOMENTUM_MIN_ITEMS`` members (a lone item is not a run).
    """
    spans = sorted(
        (float(words[c["wordIndices"][0]]["start"]),
         float(words[c["wordIndices"][-1]]["end"]), c["trigger"])
        for c in candidates
        if c.get("trigger") in MOMENTUM_TRIGGERS and c.get("wordIndices"))
    zones: list[dict] = []
    for start, end, trig in spans:
        if zones and start - zones[-1]["outEnd"] <= gap_s:
            zone = zones[-1]
            zone["outEnd"] = max(zone["outEnd"], end)
            zone["items"] += 1
            zone["triggers"].append(trig)
        else:
            zones.append({"outStart": start, "outEnd": end, "items": 1,
                          "triggers": [trig]})
    return [z for z in zones if z["items"] >= MOMENTUM_MIN_ITEMS]


def flatten_words(data: object) -> list[dict]:
    """Coerce raw list / {'words': ...} / {'transcript': [...]} to a word list."""
    if isinstance(data, list):
        return [w for w in data if isinstance(w, dict)]
    if isinstance(data, dict):
        if isinstance(data.get("words"), list):
            return [w for w in data["words"] if isinstance(w, dict)]
        if isinstance(data.get("transcript"), list):
            out: list[dict] = []
            for seg in data["transcript"]:
                out.extend(w for w in seg.get("words", []) if isinstance(w, dict))
            return out
    raise ValueError("unrecognized words JSON: expected list, {words}, or {transcript}")


def load_brands(path: Optional[str]) -> frozenset[str]:
    """Load newline-delimited brand phrases (lowercased); '#' lines ignored."""
    if not path:
        return frozenset()
    with open(path) as handle:
        lines = (ln.strip().lower() for ln in handle)
        return frozenset(ln for ln in lines if ln and not ln.startswith("#"))


def _parse_args(argv: list[str]) -> tuple[str, Optional[str], float]:
    """Parse ``<words.json> [--entities brands.txt] [--gap SECONDS]``."""
    words_path, brands_path, gap_s = None, None, TOPIC_GAP_S
    i = 0
    while i < len(argv):
        if argv[i] == "--entities" and i + 1 < len(argv):
            brands_path, i = argv[i + 1], i + 2
        elif argv[i] == "--gap" and i + 1 < len(argv):
            gap_s, i = float(argv[i + 1]), i + 2
        elif words_path is None:
            words_path, i = argv[i], i + 1
        else:
            raise ValueError(f"unexpected argument: {argv[i]}")
    if words_path is None:
        raise ValueError("missing <words.json>")
    return words_path, brands_path, gap_s


def main() -> None:
    try:
        words_path, brands_path, gap_s = _parse_args(sys.argv[1:])
        with open(words_path) as handle:
            words = flatten_words(json.load(handle))
        brands = load_brands(brands_path)
        print(json.dumps(detect_all(words, brands, gap_s), indent=2))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
