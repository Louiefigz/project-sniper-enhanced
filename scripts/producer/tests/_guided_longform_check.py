#!/usr/bin/env python3
"""Empirical proof for the TEST longform program (``_guided_longform_program``).

Nothing here is trusted by assertion alone: the beats and the form allocation
are computed in-process AND read back out of a ``graphics_planner`` subprocess
run on the written files, and ``transcript_cut_contract --previsual`` has to
return ``ok`` on the same plan/transcript/manifest.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_PRODUCER = os.path.dirname(_HERE)
for _path in (_PRODUCER, _HERE):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from _guided_longform_program import (  # noqa: E402
    OWN_SCREEN_KINDS, program_manifest, program_plan)

MIN_BEATS_90_S, MIN_BEATS_60_S = 5, 4
FIRST_BEAT_BY_S, MIN_BEAT_GAP_S = 3.5, 7.0
HOOK_WINDOW_S, HOOK_SEAM_S, BODY_SEAM_S = 180.0, 4.0, 15.0   # lint's produced-intro retention window
OUTPUT_SLACK_S = 8.0          # whole sentences are laid down only while they fit
REQUIRED_BEATS, LAST_BEAT_BY_S = 8, 90.0
MIN_ASSIGNED_BEATS, MIN_DISTINCT_KINDS = 5, 4
_SUBPROCESS_TIMEOUT_S = 300


def _dump(path: str, value: object) -> None:
    with open(path, "w") as handle:
        json.dump(value, handle, indent=2)


def _load(path: str) -> dict:
    with open(path) as handle:
        return json.load(handle)


def write_inputs(program: dict, root: str) -> dict:
    """Write transcript/manifest/plan and return the gate-facing paths."""
    source, producer = os.path.join(root, "source"), os.path.join(root, "producer")
    os.makedirs(source, exist_ok=True)
    os.makedirs(producer, exist_ok=True)
    paths = {"root": root, "dir": source,
             "transcript": os.path.join(source, "raw.transcript.json"),
             "manifest": os.path.join(source, "asset_manifest.json"),
             "plan": os.path.join(producer, "edit_plan.json")}
    _dump(paths["transcript"], program["transcript"])
    _dump(paths["manifest"], program_manifest(program))
    _dump(paths["plan"], program_plan(program))
    return paths


def direct_beats(paths: dict) -> tuple[list[dict], dict, float]:
    """Beats + allocation computed in-process from the written files."""
    from compile_timeline import compile_plan
    from graphics.form_allocation import build_form_allocation
    from graphics.intro_semantic_contract import semantic_beats
    from graphics_planner import output_words
    plan, manifest = _load(paths["plan"]), _load(paths["manifest"])
    words = output_words(plan, paths["dir"], manifest)
    out_dur = compile_plan(plan).output_duration
    beats = semantic_beats(words, out_dur, None)
    preferred = {beat["beatId"]: beat["preferredKind"] for beat in beats
                 if beat.get("preferredKind")}
    return beats, build_form_allocation(beats, preferred), out_dur


def print_beats(beats: list[dict], allocation: dict) -> None:
    """Print the beats table and the recommended assignment verbatim."""
    print(f"{'beatId':<22}{'shape':<12}{'trigger':<16}{'outStart':>9}  "
          f"{'preferredKind':<22}{'compatibleKinds / evidence'}")
    for beat in beats:
        print(f"{beat['beatId']:<22}{beat['shape']:<12}{beat['trigger']:<16}"
              f"{beat['outStart']:>9.2f}  {str(beat['preferredKind']):<22}"
              f"{','.join(beat['compatibleKinds'])}")
        print(f"{'':<22}{'':<12}{'':<16}{'':>9}  {'':<22}"
              f"evidence={beat['evidence']!r}")
    print("\nrecommendedAssignment:")
    print(json.dumps(allocation, indent=2))


def _beat_problems(beats: list[dict]) -> list[str]:
    """Coverage, opening, and spacing obligations measured in output time."""
    required = [beat for beat in beats if beat.get("decisionRequired")]
    starts = [float(beat["outStart"]) for beat in required]
    problems = []
    if len([t for t in starts if t < 90.0]) < MIN_BEATS_90_S:
        problems.append(f"fewer than {MIN_BEATS_90_S} decisionRequired beats < 90s")
    if len([t for t in starts if t < 60.0]) < MIN_BEATS_60_S:
        problems.append(f"fewer than {MIN_BEATS_60_S} decisionRequired beats < 60s")
    if not starts or starts[0] > FIRST_BEAT_BY_S:
        problems.append(f"first beat later than {FIRST_BEAT_BY_S}s")
    if len(required) != REQUIRED_BEATS or (starts and starts[-1] >= LAST_BEAT_BY_S):
        problems.append(f"expected exactly {REQUIRED_BEATS} designed beats before "
                        f"{LAST_BEAT_BY_S}s, got {len(required)} (last {starts[-1] if starts else None})")
    tight = [(left, right) for left, right in zip(starts, starts[1:])
             if right - left < MIN_BEAT_GAP_S]
    if tight:
        problems.append(f"beats closer than {MIN_BEAT_GAP_S}s: {tight}")
    return problems


def _allocation_problems(allocation: dict) -> list[str]:
    """Every assigned kind must be an own-screen scalar-spec 16:9 card."""
    assignment = allocation.get("recommendedAssignment") or []
    kinds = [str(row.get("kind")) for row in assignment]
    problems = []
    if len(assignment) < MIN_ASSIGNED_BEATS:
        problems.append(f"assignment covers {len(assignment)} beats "
                        f"(< {MIN_ASSIGNED_BEATS})")
    if len(set(kinds)) < MIN_DISTINCT_KINDS:
        problems.append(f"{len(set(kinds))} distinct kinds "
                        f"(< {MIN_DISTINCT_KINDS})")
    illegal = sorted(set(kinds) - OWN_SCREEN_KINDS)
    if illegal:
        problems.append(f"assigned kinds outside the own-screen set: {illegal}")
    return problems


def _timeline_problems(program: dict, out_dur: float) -> list[str]:
    """Output length plus the hook/body jump-cut seam cadence."""
    problems = []
    budget = float(program["meta"]["outputBudgetS"])
    if not budget - OUTPUT_SLACK_S <= out_dur <= budget:
        problems.append(f"output duration {out_dur:.3f}s outside "
                        f"[{budget - OUTPUT_SLACK_S}, {budget}]")
    if abs(out_dur - program["meta"]["outputDurationS"]) > 1e-6:
        problems.append("meta.outputDurationS disagrees with the compiled timeline")
    edges = [0.0, *program["meta"]["seamsOutS"], out_dur]
    for left, right in zip(edges, edges[1:]):
        ceiling = HOOK_SEAM_S if left < HOOK_WINDOW_S else BODY_SEAM_S
        if right - left > ceiling + 1e-9:
            problems.append(f"seam gap {right - left:.3f}s at {left:.3f}s "
                            f"exceeds {ceiling}s")
    return problems


def _run(args: list[str], label: str) -> tuple[dict, float]:
    """Run one producer CLI on the written files and parse its JSON verdict."""
    env = {**os.environ, "PYTHONPATH": _PRODUCER}
    started = time.monotonic()
    done = subprocess.run([sys.executable, *args], capture_output=True, text=True,
                          env=env, timeout=_SUBPROCESS_TIMEOUT_S)
    wall = time.monotonic() - started
    print(f"[{label}] exit={done.returncode} wall={wall:.2f}s")
    if done.stderr.strip():
        print(f"[{label}] stderr: {done.stderr.strip()[-800:]}")
    try:
        return json.loads(done.stdout), wall
    except json.JSONDecodeError:
        return {"error": done.stdout[-800:] or "no JSON on stdout"}, wall


def _planning_plan(paths: dict, advice: dict) -> str:
    """Persist the advised style decision beside the previsual cut plan.

    The previsual plan may carry only the cut lanes, so the graphics grammar the
    planner demands is applied to a planning-stage copy, exactly as the
    controller persists it after the cut is approved.
    """
    plan = _load(paths["plan"])
    target = {**plan["target"], **(advice.get("recommendedTargetFields") or {})}
    for key in advice.get("removeTargetFields") or []:
        target.pop(key, None)
    path = os.path.join(os.path.dirname(paths["plan"]), "edit_plan.planning.json")
    _dump(path, {**plan, "target": target})
    return path


def planner_problems(paths: dict, beats: list[dict], allocation: dict) -> list[str]:
    """The advised style, then the planner subprocess, must agree with (a)."""
    advice, _ = _run([os.path.join(_PRODUCER, "graphics_style_advisor.py"),
                      paths["plan"], paths["dir"], paths["manifest"]], "advisor")
    style = (advice.get("recommendedTargetFields") or {}).get("graphicsStyle")
    print(f"[advisor] graphicsStyle={style!r} signals={advice.get('signals')}")
    if not style:
        return [f"style advisor returned no recommendation: {advice}"]
    proposal, _ = _run([os.path.join(_PRODUCER, "graphics_planner.py"),
                        _planning_plan(paths, advice), paths["dir"],
                        paths["manifest"], "--json", "--style", style], "planner")
    seen = [(row["beatId"], row["shape"], round(float(row["outStart"]), 4))
            for row in proposal.get("introSemanticBeats") or []]
    want = [(row["beatId"], row["shape"], round(float(row["outStart"]), 4))
            for row in beats]
    problems = [] if seen == want else [f"planner beats differ: {seen} != {want}"]
    if (proposal.get("formAllocation") or {}) != allocation:
        problems.append("planner formAllocation differs from the direct call")
    return problems


def previsual_problems(paths: dict) -> list[str]:
    """``transcript_cut_contract --previsual`` must return ok on these files."""
    verdict, _ = _run([os.path.join(_PRODUCER, "transcript_cut_contract.py"),
                       paths["plan"], paths["dir"], paths["manifest"],
                       "--previsual"], "transcript_cut_contract")
    quality = (verdict.get("metrics") or {}).get("receipt", {}).get(
        "outputQuality", {})
    print(f"[transcript_cut_contract] ok={verdict.get('ok')} "
          f"cuts={(verdict.get('metrics') or {}).get('receipt', {}).get('cuts')} "
          f"keptWords={quality.get('keptWords')} "
          f"warnings={verdict.get('warnings')}")
    if verdict.get("ok"):
        return []
    return [f"previsual cut gate failed: {verdict.get('errors') or verdict}"]


def verify(program: dict, root: str) -> int:
    """Write, measure, and cross-check the program; 0 only when everything holds."""
    paths = write_inputs(program, root)
    beats, allocation, out_dur = direct_beats(paths)
    print_beats(beats, allocation)
    print(f"\nsourceDurationS={program['meta']['sourceDurationS']} "
          f"outputDurationS={out_dur:.4f} seams={len(program['meta']['seamsOutS'])} "
          f"beats={len(beats)}\n")
    problems = _beat_problems(beats) + _allocation_problems(allocation) \
        + _timeline_problems(program, out_dur)
    problems += planner_problems(paths, beats, allocation)
    problems += previsual_problems(paths)
    print(f"\nprogram written to {root}")
    if problems:
        print("FAILED:\n  " + "\n  ".join(problems))
        raise AssertionError(f"{len(problems)} program requirement(s) unmet")
    print("OK: every program requirement holds")
    return 0
