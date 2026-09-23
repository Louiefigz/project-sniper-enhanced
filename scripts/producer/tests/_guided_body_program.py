"""Explicit TEST-only full-body script/treatment variant, never creator copy.

The historical contrast has no numbers and uses a presenter-hole template.
This separately named program authors a numeric contrast BEFORE transcript
admission. Its chart is an eighth distinct form; no original transcript,
approved candidate, renderer limit or quality gate is changed to fit it.
The tone fixture is not real speech, ASR, listening or creative qualification.
"""
from __future__ import annotations

BODY_PROGRAM = "longform-body-300"
BODY_BUDGET_S = 312.0
CONTRAST_BEAT = ("comparison", "contrast")
CONTRAST_SENTENCE = "The system takes 10 instead of 20 minutes."
CONTRAST_CARD = {
    "kind": "chart-story",
    "values": {"type": "bars", "data": "10, 20", "labels": "system,",
               "emphasize": 0, "unit": "minutes"},
    "alternatives": ["module-scoreboard", "module-bullet-bars"],
    "reason": "The TEST source explicitly compares 10 with 20 minutes, so "
              "the closing chart paints those exact spoken quantities.",
    "selection": "A numeric contrast belongs in a two-bar chart. The system "
                 "label is spoken; the unnamed comparator has an explicitly "
                 "blank label instead of an invented source claim.",
}
BODY_STYLE_RATIONALE = (
    "This synthetic long-form program has eight source-grounded beats and "
    "no b-roll or screen share. Eight distinct native-canvas cards explicitly "
    "use own-screen presentation within the full-program takeover budget. "
    "The later numeric contrast uses a chart with no presenter hole. This "
    "is mechanical TEST coverage, not evidence of creative approval.")


def body_script(script: tuple, variant: str | None) -> tuple:
    """Choose the authored script before any timing, media or admission exists."""
    if variant is None:
        return script
    if variant != BODY_PROGRAM:
        raise ValueError("unknown TEST program variant")
    matches = [index for index, (_, beat) in enumerate(script)
               if beat == ("contrast", "comparison")]
    if len(matches) != 1:
        raise ValueError("TEST body script requires one exact closing contrast")
    return tuple((CONTRAST_SENTENCE if index == matches[0] else text, beat)
                 for index, (text, beat) in enumerate(script))


def body_kind(program: dict | None, key: tuple[str, str]) -> str | None:
    """The opt-in closing form only; every other authored choice is unchanged."""
    variant = (program or {}).get("meta", {}).get("testProgramVariant")
    if variant is not None and variant != BODY_PROGRAM:
        raise ValueError("unknown TEST treatment variant")
    return "chart-story" if variant == BODY_PROGRAM and key == CONTRAST_BEAT else None
