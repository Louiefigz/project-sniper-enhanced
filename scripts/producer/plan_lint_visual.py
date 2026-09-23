#!/usr/bin/env python3
"""plan_lint_visual — staging/legibility lint from the showpiece QC loop.

Learning-loop rules encoded from the c0679 showpiece QC panel findings
(``docs/findings/FAILURE_LEDGER.md`` — each check names its ledger row):

* ``check_first_land`` (LL-002, empty-chrome staging): a comp that enters and
  shows blank chrome before its first content land reads as a stall. The
  first DECLARED land (``spec.moduleLands[0]`` / the earliest ``atN``) must
  sit within ``MOTION["first_land"]`` of the entry's outStart — ERROR for
  own-screen cutaways (a dead full-frame canvas was the QC FAIL), WARN for
  panels (the live face carries them). Entries that declare no land times
  are skipped: the comp's internal entrance timing is not knowable here.
* ``check_contrast`` (LL-004, low-contrast accent): for comps whose accent
  paints large (>40px) text, the WCAG relative-luminance ratio of every
  spec accent color vs the comp's KNOWN bg token (the declared
  ``MOTION["contrast"]["kind_bg"]`` catalog — never guessed) must clear the
  3.0:1 large-text floor. Deterministic arithmetic, no rendering.
* ``check_left_balance`` (LL-005, left-column imbalance): a known
  left-column layout (whiteboard-list) held full-frame past
  ``MOTION["left_column"]["max_hold_s"]`` leaves ~60% of the canvas empty
  grid — WARN (taste; the operator may hold it deliberately). Kept a WARN
  rather than an ERROR because no comp exposes a fill variable today; the
  judgment override is the brain's (LESSON-004).
* ``check_row_lands`` (LL-011, progressive point reveal — operator doctrine,
  mandatory): a multi-point LIST comp on longform (the
  ``MOTION["row_lands"]["kinds"]`` catalog: glass-rail titleN rows,
  whiteboard-list itemN entries) must land each point word-locked to when
  the speaker reaches it — never all-at-once. glass-rail carries a
  ``spec.rowLands`` list (one comp-relative land per active row, filled by
  ``graphics_copy.fill_row_lands``); whiteboard-list carries per-item
  ``atN`` (``fill_list_spec``). Missing/short/mis-shaped lands on a
  ≥2-item comp = ERROR.
* ``check_form_shape`` (LL-015): the card follows the beat's INFORMATION SHAPE
  per ``MOTION["card_form_map"]``. Deterministic support: a card whose spec
  carries ≥2 numeric tokens (``claims_contract.claim_tokens`` arithmetic)
  while a declared comparative marker is spoken in its window (cleaned-token
  set membership — no regex semantics) but whose kind sits outside the
  comparison family ERRORs for produced/full longform and WARNs elsewhere.
  Needs ``words_out`` — wired in ``plan_lint.lint`` beside ``check_word_lock``.
* ``check_variety`` (LL-016, variety doctrine — MODULE_CARDS §2): tokens
  repeat, layouts don't. Produced/full longform ERRORs on adjacent repeats and
  fixed+proportional local/whole-plan floors (layers/chains exempt); lighter
  scopes WARN only on repeats.

Wired into ``plan_lint_motion.check_motion`` (same Report pattern).
"""
from __future__ import annotations

from typing import Any
import claims_contract as cc
from graphics.variety_contract import check_variety, strict_scope
from planner import motion_triggers as mt
from producer_config import MOTION
from plan_lint_contrast import check_contrast, contrast_ratio, luminance
from graphics.template_visual_contract import parse_module_lands

def _declared_first_land(spec: dict) -> float | None:
    """Earliest DECLARED comp-relative land: moduleLands[0] / min atN.

    Only reads land times the plan itself declares; malformed values are the
    module-lands / comp checks' job, so non-numerics are ignored here.
    """
    lands: list[float] = []
    try:
        lands.append(parse_module_lands(spec.get("moduleLands"))[0])
    except ValueError:
        pass  # The module schedule validator reports malformed values.
    seq = spec.get("rowLands")
    if isinstance(seq, (list, tuple)) and seq and isinstance(
            seq[0], (int, float)) and not isinstance(seq[0], bool):
        lands.append(float(seq[0]))
    for key, val in spec.items():
        if (str(key).startswith("at") and str(key)[2:].isdigit()
                and isinstance(val, (int, float))
                and not isinstance(val, bool)):
            lands.append(float(val))
    return min(lands) if lands else None


def check_first_land(plan: dict, rep: Any) -> None:
    """LL-002 — first declared content land vs the empty-chrome ceilings."""
    cfg = MOTION["first_land"]
    for i, g in enumerate(plan.get("graphicsTrack") or []):
        first = _declared_first_land(g.get("spec") or {})
        if first is None:
            continue
        own_screen = g.get("anchor") == "own-screen"
        limit = cfg["own_screen_s"] if own_screen else cfg["panel_s"]
        if first <= limit:
            continue
        msg = (f"graphicsTrack[{i}]: first content land {first:g}s after "
               f"outStart (> {limit}s) — the comp opens on empty chrome "
               "(LL-002: enter the card later, still word-locked, or land "
               "the first module on the cut)")
        rep.error(msg) if own_screen else rep.warn(msg)


def check_left_balance(plan: dict, rep: Any) -> None:
    """LL-005 — long full-frame holds of known left-column layouts."""
    cfg = MOTION["left_column"]
    max_hold = float(cfg["max_hold_s"])
    for i, g in enumerate(plan.get("graphicsTrack") or []):
        if (str(g.get("kind", "")) not in cfg["kinds"]
                or g.get("anchor") != "own-screen"):
            continue
        hold = float(g.get("outEnd", 0)) - float(g.get("outStart", 0))
        if hold > max_hold:
            rep.warn(
                f"graphicsTrack[{i}]: {g.get('kind')} is a left-column layout "
                f"held full-frame {hold:.1f}s (> {max_hold:g}s) — the right "
                "~60% is empty grid the whole hold (LL-005: shorten the hold, "
                "enter later, or pick a balanced comp)")


def _item_count(spec: dict, prefix: str, max_items: int) -> int:
    """Contiguity-free count of non-empty ``{prefix}N`` slots (N=1..max)."""
    return sum(1 for n in range(1, max_items + 1)
               if str(spec.get(f"{prefix}{n}", "") or "").strip())


def _lands_list(spec: dict, kind_cfg: dict, count: int) -> list | str:
    """The entry's per-item lands, or a defect string (LL-011 shapes).

    ``lands_key`` "at" reads per-item ``atN`` scalars (whiteboard-list);
    anything else reads a list under that spec key (glass-rail rowLands).
    """
    key = kind_cfg["lands_key"]
    if key == "at":
        lands = [spec.get(f"at{n}") for n in range(1, count + 1)]
        missing = [f"at{n}" for n, v in enumerate(lands, 1)
                   if not isinstance(v, (int, float)) or isinstance(v, bool)]
        return f"missing/non-numeric {', '.join(missing)}" if missing \
            else [float(v) for v in lands]
    lands = spec.get(key)
    if not isinstance(lands, (list, tuple)):
        return f"missing spec.{key}"
    if len(lands) != count:
        return f"spec.{key} has {len(lands)} land(s) for {count} items"
    bad = [v for v in lands
           if not isinstance(v, (int, float)) or isinstance(v, bool)]
    return f"spec.{key} has non-numeric lands" if bad \
        else [float(v) for v in lands]


def check_row_lands(plan: dict, mode: str, rep: Any) -> None:
    """LL-011 — multi-item list comps on longform need per-item lands."""
    if mode != "longform":
        return
    cfg = MOTION["row_lands"]
    gap = float(cfg["min_spacing_s"])
    for i, g in enumerate(plan.get("graphicsTrack") or []):
        kind_cfg = cfg["kinds"].get(str(g.get("kind", "")))
        if kind_cfg is None:
            continue
        spec = g.get("spec") or {}
        count = _item_count(spec, kind_cfg["item_prefix"],
                            kind_cfg["max_items"])
        if count < 2:
            continue                     # a single row is not a list build
        hold = float(g.get("outEnd", 0)) - float(g.get("outStart", 0))
        tag = f"graphicsTrack[{i}]"
        lands = _lands_list(spec, kind_cfg, count)
        if isinstance(lands, str):
            rep.error(f"{tag}: {g.get('kind')} lists {count} points but "
                      f"{lands} — LL-011/LESSON-011: every point of a "
                      "multi-item list comp must land word-locked to when "
                      "the speaker reaches it (fill via "
                      "graphics_copy.fill_row_lands / fill_list_spec), "
                      "never all-at-once")
            continue
        for k, t in enumerate(lands):
            if not 0.0 <= t <= hold + 1e-6:
                rep.error(f"{tag}: point land {t:g}s is outside the "
                          f"[0,{hold:.2f}]s hold (LL-011)")
            if k and t - lands[k - 1] < gap:
                rep.error(f"{tag}: point lands {lands[k - 1]:g}s → {t:g}s "
                          f"are closer than {gap:g}s — stacked lands read "
                          "as all-at-once (LL-011)")


def check_visual(plan: dict, rep: Any) -> None:
    """All learning-loop visual checks (called from plan_lint_motion).

    ``check_row_lands`` (LL-011) and ``check_variety`` (LL-016) are
    mode-gated, so plan_lint_motion calls them separately with the mode in
    hand; ``check_form_shape`` (LL-015) needs kept words, so plan_lint.lint
    calls it beside ``check_word_lock``.
    """
    check_first_land(plan, rep)
    check_contrast(plan, rep)
    check_left_balance(plan, rep)


def _entry_claim_tokens(spec: dict) -> list[str]:
    """Numeric copy tokens across a card's spec strings — reuses the claims
    gate's arithmetic tokenizer (``evidence*``/``icon*`` slots stay exempt),
    so form lint and truth gate can never disagree on what a number is."""
    return [tok for _path, text in cc._spec_strings(spec)
            for tok in cc.claim_tokens(text)]


def check_form_shape(plan: dict, words_out: list[dict], rep: Any) -> None:
    """LL-015 — comparison-shaped info on a non-comparison card form.

    DETERMINISM: the numeric side is ``claims_contract.claim_tokens``
    (arithmetic parse — digits, $/%/K/M/B edges, never regex), and the
    comparative marker is cleaned-token SET MEMBERSHIP against the declared
    ``MOTION["form_shape"]["comparative_words"]`` catalog — the same
    declared-token-catalog pattern as ``motion_triggers.CONTRAST_WORDS`` and
    the LL-012 chrome gate. Deliberately NARROW (both conditions must hold)
    and fail-closed only for produced/full longform: whether a lighter edit's
    beat truly compares remains the brain's LESSON-029 call.
    """
    cfg = MOTION["form_shape"]
    strict = strict_scope(plan, str((plan.get("target") or {}).get("mode", "")),
                          cfg["strict_scopes"])
    family = MOTION["card_form_map"]["comparison"]
    layers = MOTION["variety"]["layer_kinds"]
    near = float(cfg["near_s"])
    for i, g in enumerate(plan.get("graphicsTrack") or []):
        kind = str(g.get("kind", ""))
        if kind in family or kind in layers:
            continue
        toks = _entry_claim_tokens(g.get("spec") or {})
        if len(toks) < int(cfg["numeric_min"]):
            continue
        lo = float(g.get("outStart", 0.0)) - near
        hi = float(g.get("outEnd", 0.0)) + near
        spoken = {mt._clean(mt._word_text(w)) for w in words_out
                  if lo <= float(w.get("start", 1e18)) <= hi}
        marks = spoken & set(cfg["comparative_words"])
        if not marks:
            continue
        message = (
            f"graphicsTrack[{i}]: {kind} carries {len(toks)} numeric tokens "
            f"({', '.join(toks)}) while the window [{lo:.1f},{hi:.1f}]s "
            f"speaks {sorted(marks)} — comparison-shaped info wants a "
            f"comparison form ({', '.join(family)}); numbers on a plain "
            "card are a form mismatch (LL-015/LESSON-029: pick the form by "
            "the INFORMATION SHAPE, MOTION['card_form_map'])")
        rep.error(message) if strict else rep.warn(message)
