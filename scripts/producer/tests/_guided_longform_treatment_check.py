#!/usr/bin/env python3
"""Empirical proof for the TEST longform TREATMENT copy.

Nothing here is trusted by assertion alone. The variable sets are judged
against the MEASURED ``comp_capabilities`` matrix, every card is pushed
through ``graphics.template_contract.entry_errors`` and
``graphics.template_visual_contract.visual_entry_errors`` at its authored
minimum hold, the clean-hook receipt is judged by
``intro_transition_contract.valid_clean_hook_receipt`` — and then a full
synthetic ``edit_plan.json`` is written beside the program's manifest and
transcript and run through the REAL CLIs (``plan_lint``, ``hook_contract``,
``claims_contract``, ``operator_intent_contract``), whose verdicts are printed
verbatim.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_PRODUCER = os.path.dirname(_HERE)
for _path in (_PRODUCER, _HERE):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from _cut_preview_fixture import PROJECT_INTENT              # noqa: E402
from _guided_longform_check import direct_beats, write_inputs  # noqa: E402
from _guided_longform_program import build_program           # noqa: E402
from _guided_longform_treatment import (                     # noqa: E402
    GRAPHICS_STYLE, GRAPHICS_STYLE_RATIONALE, MAXIMUM_HOLD_S, anchor_for,
    build_treatment, kept_words, minimum_hold_s, program_beats,
    write_treatment)
from compile_timeline import compile_plan                    # noqa: E402
from graphics.comp_capabilities import capability_matrix     # noqa: E402
from graphics.template_contract import entry_errors          # noqa: E402
from graphics.template_visual_contract import visual_entry_errors  # noqa: E402
from intro_transition_contract import (intro_seams,          # noqa: E402
                                       valid_clean_hook_receipt)
from producer_config import (HOOK_CONTRACT_WINDOW_S, MODES,  # noqa: E402
                             MOTION)

#: The produced first-minute dressing floors plan_lint_motion fails closed on.
LONGFORM_PACING = MODES["longform"]["pacing"]

# plan_lint_motion._check_module_lands rejects an empty-string land field, so
# the compiled spec carries a land key only when it actually schedules builds.
_TIMING_CONTROLS = ("moduleLands", "rowLands", "statementLands")
_ASSET_KEY = re.compile(r"src|file|icon|avatar|image|url|asset", re.IGNORECASE)
_SUBPROCESS_TIMEOUT_S = 300
_MIN_REASON_CHARS = 20


def compiled_spec(row: dict) -> dict:
    """The authored variables as a renderer spec (empty land keys dropped)."""
    spec = {item["name"]: item["value"] for item in row["variables"]}
    return {key: value for key, value in spec.items()
            if not (key in _TIMING_CONTROLS and value == "")}


def _variable_problems(row: dict) -> list[str]:
    """Rule 1 — completeness, catalog membership, type and asset parity."""
    capability = capability_matrix().get(row["kind"]) or {}
    defaults = capability.get("specDefaults") or {}
    names = [item["name"] for item in row["variables"]]
    problems = []
    if sorted(names) != sorted(defaults) or len(set(names)) != len(names):
        problems.append(f"{row['kind']}: variables {names} do not cover every "
                        f"measured default {sorted(defaults)} exactly once")
    for item in row["variables"]:
        problems += _one_variable_problems(row["kind"], item, defaults)
    return problems


def _one_variable_problems(kind: str, item: dict, defaults: dict) -> list[str]:
    """Catalog membership, JSON type parity, and the asset-slot blank rule."""
    name, value = item["name"], item["value"]
    if name not in defaults:
        return [f"{kind}: spec.{name} is outside the measured contract"]
    if type(value) is not type(defaults[name]):
        return [f"{kind}: spec.{name} is {type(value).__name__}, measured "
                f"default is {type(defaults[name]).__name__}"]
    if _ASSET_KEY.search(name) and not (defaults[name] == "" and value == ""):
        return [f"{kind}: asset-bearing spec.{name} must stay the exact empty "
                "default; guided work resolves assets separately"]
    return []


def _contract_problems(row: dict) -> list[str]:
    """Rules 2+3 — the real template and visible-completeness validators."""
    start = float(row["outStart"])
    entry = {"id": f"probe-{row['beatId']}", "kind": row["kind"],
             "spec": compiled_spec(row), "outStart": start,
             "outEnd": start + float(row["minimumHoldS"]),
             "anchor": "own-screen", "reason": row["reason"]}
    return [f"{row['kind']}: {issue}" for issue in
            entry_errors(entry) + visual_entry_errors(entry)]


def _hold_problems(row: dict, beat: dict) -> list[str]:
    """Rule 6 — the authored floor/ceiling and the land/PIP field bans."""
    spec, problems = compiled_spec(row), []
    if abs(row["minimumHoldS"] - minimum_hold_s(row["kind"], beat)) > 1e-9:
        problems.append(f"{row['kind']}: minimumHoldS is not the floor "
                        f"{minimum_hold_s(row['kind'], beat):.2f}s")
    if row["maximumHoldS"] != MAXIMUM_HOLD_S \
            or row["minimumHoldS"] > MAXIMUM_HOLD_S:
        problems.append(f"{row['kind']}: hold band is outside "
                        f"[{MOTION['hold_min_s']['longform']}, "
                        f"{MAXIMUM_HOLD_S}]s")
    if spec.get("presenterFrame", False) is not False:
        problems.append(f"{row['kind']}: presenterFrame must stay false — the "
                        "first opening profile renders no PIP hole")
    if "moduleLands" in spec and not isinstance(spec["moduleLands"], list):
        problems.append(f"{row['kind']}: spec.moduleLands must be an "
                        "increasing list when present")
    return problems


def _selection_problems(row: dict, beat: dict) -> list[str]:
    """Rule 7 — the alternatives the beat's own compatible forms allow."""
    alternatives = row["alternativesConsidered"]
    needed = min(2, max(0, len(beat["compatibleKinds"]) - 1))
    problems = []
    if len(set(alternatives)) != len(alternatives) \
            or row["kind"] in alternatives \
            or any(kind not in beat["compatibleKinds"] for kind in alternatives):
        problems.append(f"{row['kind']}: alternativesConsidered "
                        f"{alternatives} must be unique other members of "
                        f"{beat['compatibleKinds']}")
    if len(alternatives) < needed:
        problems.append(f"{row['kind']}: considered {len(alternatives)} "
                        f"alternative(s); needs {needed}")
    for field in ("reason", "selectionReason"):
        if len(str(row[field]).strip()) < _MIN_REASON_CHARS:
            problems.append(f"{row['kind']}: {field} needs "
                            f"{_MIN_REASON_CHARS}+ characters")
    return problems


def treatment_problems(treatment: dict, beats: list[dict]) -> list[str]:
    """Every per-beat rule, judged by the real contract modules."""
    by_id = {beat["beatId"]: beat for beat in beats}
    problems = []
    if len(treatment["beats"]) != len(beats):
        problems.append(f"treatment covers {len(treatment['beats'])} of "
                        f"{len(beats)} decisionRequired beats")
    for row in treatment["beats"]:
        beat = by_id.get(row["beatId"])
        if beat is None:
            problems.append(f"treatment beat {row['beatId']} is not a "
                            "deterministic transcript beat")
            continue
        problems += _variable_problems(row) + _contract_problems(row) \
            + _hold_problems(row, beat) + _selection_problems(row, beat)
    return problems


def seam_problems(treatment: dict, program: dict) -> list[str]:
    """Rule 8 — the clean-hook receipt must satisfy the shared validator."""
    seams = intro_seams(program["cutTrack"],
                        float(HOOK_CONTRACT_WINDOW_S["longform"]))
    receipt = clean_hook_receipt(treatment)
    plan = {"transitions": [], "transitionRationale": receipt}
    if valid_clean_hook_receipt(plan, seams):
        return []
    return [f"clean-hook receipt does not cover intro seams {seams}: "
            f"{json.dumps(receipt)[:400]}"]


def clean_hook_receipt(treatment: dict) -> dict:
    """The plan-shaped transitionRationale built from the authored seam rows."""
    return {"decision": "clean-hook",
            "reason": "Every intro seam joins two complete sentences on their "
                      "own boundary, so a rendered transition would decorate "
                      "a join the narration already resolves.",
            "seams": [{"outTime": row["outTime"], "evidence": row["evidence"]}
                      for row in treatment["seamEvidence"]]}


def _out_end(start: float, minimum: float, seams: list[float],
             out_dur: float) -> float:
    """The first cut seam at or after the floor — hold-to-cut comps die on a cut."""
    return next((seam for seam in seams if seam >= start + minimum - 1e-9),
                out_dur)


def _graphics(treatment: dict, beats: list[dict], seams: list[float],
              out_dur: float) -> tuple[list[dict], list[dict]]:
    """The graphicsTrack entries and their bound graphicsDecisions rows."""
    by_id = {beat["beatId"]: beat for beat in beats}
    track, decisions = [], []
    for index, row in enumerate(treatment["beats"]):
        start = float(row["outStart"])
        graphic_id = f"g-test-{index + 1}"
        track.append({
            "id": graphic_id, "kind": row["kind"], "spec": compiled_spec(row),
            "outStart": start,
            "outEnd": _out_end(start, float(row["minimumHoldS"]), seams, out_dur),
            "anchor": row["anchor"], "reason": row["reason"],
            "semanticBeatId": row["beatId"]})
        decisions.append({
            "beatId": row["beatId"], "decision": "graphic",
            "reason": row["reason"], "kind": row["kind"],
            "alternativesConsidered": row["alternativesConsidered"],
            "selectionReason": row["selectionReason"],
            "graphicId": graphic_id})
    return track, decisions


def build_edit_plan(program: dict, treatment: dict,
                    beats: list[dict]) -> dict:
    """The full synthetic plan the four production CLIs are run against."""
    from _guided_longform_program import program_plan
    plan = program_plan(program)
    timeline = compile_plan(plan)
    seams = [round(segment.out_start, 4) for segment in timeline.segments[1:]]
    track, decisions = _graphics(treatment, beats, seams,
                                 round(timeline.output_duration, 4))
    target = {**plan["target"], "graphicsStyle": GRAPHICS_STYLE,
              "graphicsStyleRationale": treatment["graphicsStyleRationale"],
              "lanes": PROJECT_INTENT["intent"]["lanes"]}
    return {**plan, "target": target, "graphicsTrack": track,
            "graphicsDecisions": decisions, "transitions": [],
            "transitionRationale": clean_hook_receipt(treatment)}


def _run(args: list[str], label: str) -> tuple[dict, float]:
    """Run one producer CLI and print its verdict verbatim."""
    env = {**os.environ, "PYTHONPATH": _PRODUCER}
    started = time.monotonic()
    done = subprocess.run([sys.executable, *args], capture_output=True,
                          text=True, env=env, timeout=_SUBPROCESS_TIMEOUT_S)
    wall = time.monotonic() - started
    print(f"\n===== {label}: exit={done.returncode} wall={wall:.2f}s =====")
    print(done.stdout.strip() or "<no stdout>")
    if done.stderr.strip():
        print(f"[{label}] stderr: {done.stderr.strip()[-1200:]}")
    try:
        return json.loads(done.stdout), wall
    except json.JSONDecodeError:
        return {"ok": False, "errors": [done.stdout[-500:] or "no JSON"]}, wall


def _cli_rows(paths: dict) -> list[tuple[str, list[str]]]:
    """(label, argv) for each gate CLI, in the order the skill runs them."""
    expected = json.dumps(PROJECT_INTENT["intent"])
    return [
        ("plan_lint", [os.path.join(_PRODUCER, "plan_lint.py"), paths["plan"],
                       paths["manifest"], paths["dir"]]),
        ("hook_contract", [os.path.join(_PRODUCER, "hook_contract.py"),
                           paths["plan"], paths["dir"], paths["manifest"]]),
        ("claims_contract", [os.path.join(_PRODUCER, "claims_contract.py"),
                             paths["plan"], paths["dir"], paths["manifest"]]),
        ("operator_intent_contract",
         [os.path.join(_PRODUCER, "operator_intent_contract.py"),
          paths["plan"], "--expected-json", expected]),
    ]


def run_gates(paths: dict) -> list[str]:
    """Run every gate CLI; return the problems for the ones that rejected."""
    problems, warnings = [], []
    for label, argv in _cli_rows(paths):
        verdict, _wall = _run(argv, label)
        warnings += [f"{label}: {text}" for text in verdict.get("warnings") or []]
        if not verdict.get("ok"):
            problems.append(f"{label} rejected the plan: "
                            f"{json.dumps(verdict.get('errors'))[:1500]}")
    print("\nwarnings (non-blocking):")
    print("  " + "\n  ".join(warnings) if warnings else "  none")
    return problems


def _write_plan(paths: dict, plan: dict) -> None:
    with open(paths["plan"], "w") as handle:
        json.dump(plan, handle, indent=2)


def verify(root: str, duration_s: float = 96.0) -> int:
    """Write program + treatment + plan, then prove them; 0 only when clean."""
    program = build_program(duration_s)
    paths = write_inputs(program, root)
    beats, allocation, out_dur = direct_beats(paths)
    required = [beat for beat in beats if beat.get("decisionRequired")]
    treatment = build_treatment(program, required, allocation)
    treatment_path = os.path.join(paths["dir"], "test-treatment.json")
    write_treatment(treatment_path, treatment)
    print(json.dumps(treatment, indent=2))
    plan = build_edit_plan(program, treatment, required)
    _write_plan(paths, plan)
    problems = treatment_problems(treatment, required) \
        + seam_problems(treatment, program) \
        + _coverage_problems(plan, out_dur) \
        + _in_process_parity(program, beats, allocation)
    problems += run_gates(paths)
    print(f"\nprogram+treatment written to {root}")
    print(f"treatment: {treatment_path}")
    print(f"kept words: {len(kept_words(program))}  output: {out_dur:.3f}s")
    if problems:
        print("FAILED:\n  " + "\n  ".join(problems))
        raise AssertionError(f"{len(problems)} treatment requirement(s) unmet")
    print("OK: every treatment requirement holds")
    return 0


def _in_process_parity(program: dict, beats: list[dict],
                       allocation: dict) -> list[str]:
    """The fixture authors from ``program_beats``; it must equal the file path."""
    seen_beats, seen_allocation = program_beats(program)
    if seen_beats == beats and seen_allocation == allocation:
        return []
    return ["program_beats disagrees with the on-disk planner path used by "
            "_guided_longform_check.direct_beats"]


def _coverage_problems(plan: dict, out_dur: float) -> list[str]:
    """The own-screen budget and the produced first-minute dressing floor."""
    from planner.graphics_planner_longform import own_screen_cap
    from planner.pacing import nonhead_share
    track = plan["graphicsTrack"]
    own = sum(1 for row in track if row["anchor"] == "own-screen")
    cap = max(MOTION["takeover_max_count"]["longform"], own_screen_cap(out_dur))
    floor = float(LONGFORM_PACING["hook60_min_nonhead_share"])
    share = nonhead_share(plan, min(60.0, out_dur))
    problems = []
    if own > cap:
        problems.append(f"{own} own-screen takeovers exceed the {cap} budget")
    if share < floor:
        problems.append(f"non-head visuals cover {share:.1%} of the first "
                        f"minute, below the {floor:.0%} produced floor")
    print(f"\nown-screen takeovers: {own}/{cap}   "
          f"first-minute non-head share: {share:.1%} (floor {floor:.0%})")
    return problems
