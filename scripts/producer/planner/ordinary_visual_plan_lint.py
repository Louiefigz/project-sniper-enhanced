#!/usr/bin/env python3
"""Gate an ordinary edit plan against its allocated VISUAL-PLAN.json."""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from planner.visual_plan_contract import (  # noqa: E402
    VisualPlanContractError,
    invalidation_inputs,
    validate_visual_plan,
)
from planner.visual_plan_admission import load_catalog_authority  # noqa: E402
from planner.visual_plan_receipts import authority_pin  # noqa: E402
from planner.ordinary_visual_plan_semantics import (  # noqa: E402
    ExecutionBindingContext,
    StyleMappingContext,
    check_expected_authority,
    check_execution_binding,
    check_style_mapping,
)
from planner.ordinary_visual_plan_timing import (  # noqa: E402
    cut_windows,
    row_window,
    timing_matches,
)
MAX_JSON_BYTES, MAX_ERRORS = 4 * 1024 * 1024, 128
SHA256 = frozenset("0123456789abcdef")
LANES = frozenset(("graphicsTrack", "transitions", "punchIns", "cutTrack",
                   "brollTrack"))
class Report:
    """Bounded machine-readable gate verdict."""
    def __init__(self) -> None:
        self.errors: list[str] = []
    def error(self, message: str) -> None:
        """Record one bounded diagnostic."""
        if len(self.errors) < MAX_ERRORS:
            self.errors.append(message[:2000])
    def emit(self, decisions: int = 0) -> int:
        """Print the gate contract and return its exit code."""
        value = {"ok": not self.errors, "errors": self.errors, "warnings": [],
                 "metrics": {"applicationDecisions": decisions}}
        print(json.dumps(value, indent=2, sort_keys=True))
        return 0 if not self.errors else 1
@dataclass
class _Runtime:
    plan: dict
    cut_windows: list[tuple[float, float]]
    seen: set[tuple[str, int]]
    records: dict
    report: Report
def _read_object(raw_path: str, label: str) -> tuple[bytes, dict]:
    path = Path(raw_path).expanduser()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be one regular non-symlink file")
    size = path.stat().st_size
    if size < 2 or size > MAX_JSON_BYTES:
        raise ValueError(f"{label} exceeds the bounded read size")
    data = path.read_bytes()
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} root must be an object")
    return data, value
def _sha(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 \
        and not (set(value) - SHA256)
def _exact_object(value: object, keys: set[str], label: str,
                  report: Report) -> dict | None:
    if not isinstance(value, dict):
        report.error(f"{label} must be an object")
        return None
    actual = set(value)
    if actual != keys:
        report.error(f"{label} fields must be exactly {sorted(keys)}")
        return None
    return value
def _binding_errors(application: dict,
                    context: tuple[bytes, dict, tuple[str | None, str | None]],
                    report: Report) -> None:
    data, identity, expected = context
    binding = _exact_object(application.get("visualPlan"),
                            {"byteHash", "visualPlanSha256"},
                            "visualPlanApplication.visualPlan", report)
    if binding is None:
        return
    actual_byte = hashlib.sha256(data).hexdigest()
    actual_plan = identity["visualPlanSha256"]
    if binding.get("byteHash") != actual_byte:
        report.error("visualPlanApplication byteHash does not bind VISUAL-PLAN.json")
    if binding.get("visualPlanSha256") != actual_plan:
        report.error("visualPlanApplication visualPlanSha256 is stale")
    if expected[0] is not None and actual_byte != expected[0]:
        report.error("VISUAL-PLAN.json bytes differ from the controller binding")
    if expected[1] is not None and actual_plan != expected[1]:
        report.error("VISUAL-PLAN.json identity differs from the controller binding")
def _element_ref(value: object, label: str,
                 runtime: _Runtime) -> tuple[str, int, dict] | None:
    ref = _exact_object(value, {"lane", "index"}, label, runtime.report)
    if ref is None:
        return None
    lane, index = ref.get("lane"), ref.get("index")
    if lane not in LANES or isinstance(index, bool) or not isinstance(index, int):
        runtime.report.error(f"{label} must name a supported lane and integer index")
        return None
    rows = runtime.plan.get(lane)
    if not isinstance(rows, list) or not (0 <= index < len(rows)):
        runtime.report.error(f"{label} points outside {lane}")
        return None
    row = rows[index]
    if not isinstance(row, dict):
        runtime.report.error(f"{label} target must be an object")
        return None
    window = runtime.cut_windows[index] \
        if lane == "cutTrack" and index < len(runtime.cut_windows) else None
    return lane, index, {"row": row, "window": window}
def _check_elements(row: dict, decision: tuple[dict, str, dict],
                    runtime: _Runtime) -> None:
    opportunity, modality, _candidate = decision
    elements = row.get("elements")
    execution = row.get("execution")
    expected_execution = {"presenter": "presenter-hold", "omit": "intentional-omit"} \
        .get(modality, "elements")
    if execution != expected_execution:
        runtime.report.error(
            f"{row.get('opportunityId')}: execution does not match modality {modality}")
    if not isinstance(elements, list) or len(elements) > 8:
        runtime.report.error(f"{row.get('opportunityId')}: elements must be a bounded array")
        return
    if modality == "omit":
        if elements:
            runtime.report.error(
                f"{row.get('opportunityId')}: omit decisions cannot bind elements")
        context = ExecutionBindingContext(runtime.plan, row, opportunity, _candidate,
                                          runtime.records, opportunity["_fps"], [],
                                          str(row.get("opportunityId")))
        check_execution_binding(context, runtime.report.error)
        return
    if not elements:
        runtime.report.error(
            f"{row.get('opportunityId')}: selected visual has no executable element")
        return
    _check_element_windows(row, elements, decision, runtime)

def _check_element_windows(row: dict, elements: list,
                           decision: tuple[dict, str, dict], runtime: _Runtime) -> None:
    opportunity, modality, candidate = decision
    fps = opportunity["_fps"]
    expected = (row["timing"]["startFrame"] / fps,
                row["timing"]["endFrameExclusive"] / fps)
    tolerance = 0.5 / fps + 1e-6
    resolved_elements = []
    for index, value in enumerate(elements):
        label = f"{row.get('opportunityId')}.elements[{index}]"
        resolved = _element_ref(value, label, runtime)
        if resolved is None:
            continue
        lane, position, target = resolved
        key = (lane, position)
        if key in runtime.seen:
            runtime.report.error(f"{label} duplicates an element used by another decision")
        runtime.seen.add(key)
        resolved_elements.append({"lane": lane, "index": position,
                                  "row": target["row"]})
        window = row_window(lane, target["row"], target["window"])
        if window is None or not timing_matches(lane, window, expected, tolerance):
            runtime.report.error(f"{label} timing does not realize the allocated opportunity")
        if lane == "graphicsTrack":
            style = StyleMappingContext(
                runtime.plan, target["row"], candidate["composition"], label)
            check_style_mapping(style, runtime.report.error)
    context = ExecutionBindingContext(runtime.plan, row, opportunity, candidate,
                                      runtime.records, fps, resolved_elements,
                                      str(row.get("opportunityId")))
    check_execution_binding(context, runtime.report.error)

def _validate_decision(row_value: object, expected: dict, opportunity: dict,
                       runtime: tuple[dict, set[tuple[str, int]], Report]) -> None:
    plan, seen, report = runtime
    keys = {"opportunityId", "candidateId", "modality", "execution",
            "timing", "elements", "binding"}
    row = _exact_object(row_value, keys, "visualPlanApplication decision", report)
    if row is None:
        return
    for field in ("opportunityId", "candidateId", "modality"):
        if row.get(field) != expected[field]:
            report.error(f"visualPlanApplication {field} does not match selected allocation")
    timing = _exact_object(row.get("timing"), {"startFrame", "endFrameExclusive"},
                           f"{row.get('opportunityId')}.timing", report)
    if timing is None:
        return
    if any(isinstance(value, bool) or not isinstance(value, int)
           for value in timing.values()):
        report.error(f"{row.get('opportunityId')}: timing values must be integers")
        return
    if timing != opportunity["timing"]:
        report.error(f"{row.get('opportunityId')}: timing differs from its opportunity")
        return
    candidate = next(item for item in opportunity["candidates"]
                     if item["id"] == expected["candidateId"])
    _check_elements(row, (opportunity, str(expected["modality"]), candidate),
                    _Runtime(plan, opportunity["_cutWindows"], seen,
                             opportunity["_catalogRecords"], report))

def _missing_application(visual: dict, data: bytes,
                         report: Report, receipt_authority: dict | None) -> None:
    identity = invalidation_inputs(visual, receipt_authority)
    report.error("visualPlanApplication is required; bind byteHash "
                 f"{hashlib.sha256(data).hexdigest()} and visualPlanSha256 "
                 f"{identity['visualPlanSha256']}")
    opportunities = {row["id"]: row for row in visual["opportunities"]}
    for row in visual["allocation"]["decisions"]:
        timing = opportunities[row["opportunityId"]]["timing"]
        report.error(f"required mapping {row['opportunityId']} -> "
                     f"{row['candidateId']} ({row['modality']}) at {timing}")

def _check_application(
    inputs: tuple[dict, dict, bytes, tuple[str | None, str | None]],
    report: Report,
    receipt_authority: dict | None = None,
) -> int:
    plan, visual, data, expected_hashes = inputs
    if plan.get("visualPlanApplication") is None:
        _missing_application(visual, data, report, receipt_authority)
        return 0
    app = _exact_object(plan.get("visualPlanApplication"),
                        {"schemaVersion", "route", "visualPlan", "decisions"},
                        "visualPlanApplication", report)
    if app is None:
        return 0
    identity = invalidation_inputs(visual, receipt_authority)
    if app.get("schemaVersion") != 1 or app.get("route") != "ordinary":
        report.error("visualPlanApplication must be schemaVersion 1 on route ordinary")
    _binding_errors(app, (data, identity, expected_hashes), report)
    allocation = visual["allocation"]
    if allocation["status"] != "allocated" or allocation["route"] != "ordinary":
        report.error("VISUAL-PLAN.json must allocate the whole project to ordinary")
        return 0
    decisions = app.get("decisions")
    expected = allocation["decisions"]
    if not isinstance(decisions, list) or len(decisions) != len(expected):
        report.error("visualPlanApplication decisions must cover every allocation decision")
        return len(decisions) if isinstance(decisions, list) else 0
    opportunities = {row["id"]: dict(row) for row in visual["opportunities"]}
    records = load_catalog_authority(visual["catalogPin"])["records"]
    fps = visual["project"]["fps"]["numerator"] / visual["project"]["fps"]["denominator"]
    cuts, seen = cut_windows(plan, report.error), set()
    for actual, selected in zip(decisions, expected):
        opportunity = opportunities[selected["opportunityId"]]
        opportunity["_fps"], opportunity["_cutWindows"] = fps, cuts
        opportunity["_catalogRecords"] = records
        _validate_decision(actual, selected, opportunity, (plan, seen, report))
    return len(decisions)

def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("edit_plan")
    parser.add_argument("visual_plan")
    parser.add_argument("--expected-byte-hash")
    parser.add_argument("--expected-visual-plan-sha256")
    parser.add_argument("--expected-project-json")
    parser.add_argument("--expected-catalog-pin-sha256")
    parser.add_argument("--expected-controller-authority-sha256")
    parser.add_argument("--receipt-authority")
    return parser

def main(argv: list[str] | None = None) -> int:
    """Validate one ordinary edit plan against controller-bound visual direction."""
    args = _parser().parse_args(argv)
    report = Report()
    expected = (args.expected_byte_hash, args.expected_visual_plan_sha256)
    if any(value is not None and not _sha(value) for value in (
            *expected, args.expected_catalog_pin_sha256,
            args.expected_controller_authority_sha256)):
        report.error("controller expected hashes must be lowercase SHA-256 values")
        return report.emit()
    try:
        _, plan = _read_object(args.edit_plan, "edit plan")
        data, raw_visual = _read_object(args.visual_plan, "visual plan")
        receipt_authority = (authority_pin(args.receipt_authority)
                             if args.receipt_authority else None)
        visual = validate_visual_plan(raw_visual, receipt_authority)
        check_expected_authority(visual, (args.expected_project_json,
                                 args.expected_catalog_pin_sha256,
                                 args.expected_controller_authority_sha256), report.error)
        decisions = _check_application(
            (plan, visual, data, expected), report, receipt_authority)
    except (OSError, ValueError, VisualPlanContractError) as exc:
        report.error(f"load failed: {exc}")
        decisions = 0
    return report.emit(decisions)

if __name__ == "__main__":
    raise SystemExit(main())
