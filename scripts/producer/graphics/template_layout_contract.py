"""Closed native layout intent; observed readability requires actual output QA."""
from __future__ import annotations


def _agenda_errors(entry: dict, spec: dict) -> list[str]:
    """Retain the existing upper agenda's explicit copy and canvas bounds."""
    active = [index for index in range(1, 6)
              if isinstance(spec.get(f"title{index}"), str)
              and spec[f"title{index}"].strip()]
    errors = []
    if not 1 <= len(active) <= 3:
        errors.append("agenda-slide upper split requires one to three explicit steps; do not drop requested copy")
    if entry.get("anchor") != "own-screen":
        errors.append("agenda-slide upper split requires the native own-screen canvas")
    return errors


def _pipeline_errors(entry: dict, spec: dict, layout: str) -> list[str]:
    """Require complete two-to-six-node teaching diagrams without presenter holes."""
    raw = spec.get("nodes")
    nodes = raw.split("|") if isinstance(raw, str) and raw.strip() else []
    label = "upper" if layout == "caption-safe-upper-v1" else "teaching"
    errors = []
    if not 2 <= len(nodes) <= 6:
        errors.append(f"nateherk-pipeline {label} layout requires two to six explicit nodes; never drop copy")
    presenter = spec.get("presenterFrame", False)
    if entry.get("anchor") != "own-screen" or (presenter is not False and presenter != "false"):
        errors.append(f"nateherk-pipeline {label} layout requires own-screen without a presenter hole")
    exit_kind = spec.get("exit", "hold")
    if label == "upper" and exit_kind != "hold":
        errors.append("nateherk-pipeline upper layout requires hold exit; blurred paint is unqualified")
    if label == "teaching" and exit_kind not in ("hold", "blur-recede"):
        errors.append("nateherk-pipeline teaching layout requires hold or blur-recede exit")
    return errors


def native_layout_errors(entry: dict, spec: dict) -> list[str]:
    """Validate declared layout intent without claiming measured caption safety.

    Original full-canvas layouts retain their historical content classes.
    Caption-safe layouts keep their narrower, separately observed contract.
    The teaching layout deliberately uses the whole frame and reserves no
    caption or presenter region; callers must not treat its name as such proof.
    """
    kind = entry.get("kind")
    layout = spec.get("layout", "full-canvas")
    if kind not in ("agenda-slide", "nateherk-pipeline") or layout == "full-canvas":
        return []
    supported = ["caption-safe-upper-v1"]
    if kind == "nateherk-pipeline":
        supported.append("teaching-full-width-v1")
    if layout not in supported:
        return [f"{kind} spec.layout must name an explicit supported native layout"]
    if kind == "agenda-slide":
        return _agenda_errors(entry, spec)
    return _pipeline_errors(entry, spec, layout)
