"""Pure full-editability and translator preflight for Palmier handoff."""
from __future__ import annotations

from palmier.parity import analyze_parity
from palmier.translate import TranslateError, TranslateRequest, translate


def parity_block(report: dict) -> str | None:
    """Return the first malformed/unsafe visual-mirror blocker, if any."""
    blockers = report.get("mirrorBlockers") or report.get("syncBlockers") or []
    if not blockers:
        return None
    first = blockers[0]
    return ("Palmier visual mirror is unsafe: "
            f"{first.get('label', first.get('lane', 'edit'))} — "
            f"{first.get('message', 'malformed or unknown plan structure')}")


def preflight(plan: dict, request: TranslateRequest | None,
              authority_block: str | None = None) -> dict:
    """Return a fail-closed visual-master mirror + editability verdict."""
    parity = analyze_parity(plan)
    translator_block: str | None = authority_block
    steps: list[dict] = []
    if request is not None and translator_block is None:
        try:
            steps = translate(plan, request)
        except (TranslateError, KeyError, TypeError, ValueError) as exc:
            translator_block = str(exc)
    ready = parity.get("mirrorReady") is True and translator_block is None
    return {
        "preflight": True,
        "ok": ready,
        "mirrorReady": ready,
        "mirrorMode": parity.get("mirrorMode", "blocked"),
        "blocked": translator_block or parity_block(parity),
        "translatorBlocked": translator_block,
        "steps": len(steps),
        "warnings": [step["message"] for step in steps if step["op"] == "warn"],
        "parity": parity,
    }
