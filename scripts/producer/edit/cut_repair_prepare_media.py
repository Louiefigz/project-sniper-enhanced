#!/usr/bin/env python3
"""Render the exact private media candidate selected by live P2 analysis."""
from __future__ import annotations

import argparse
import json
import os
import shutil

from edit.compatibility_projection import stable_digest
from edit.cut_repair_context_sources import stable_json
from edit.cut_repair_review_plan import (
    lead_ms,
    review_plan,
    review_plan_result,
)
from edit.cut_repair_route import run
from edit.exact_timing import PositiveRational, ProjectClock
from edit.picture_lock_common import canonical_json, content_hash
from edit.repair_composite import (
    RepairCompositeRequest,
    render_repair_composite,
)
from edit.repair_fragment import render_repair_fragment
from edit.repair_fragment_contracts import (
    RepairFragmentRequest,
    RepairMediaTools,
)
from fingerprints import file_sha256


class PreparationError(RuntimeError):
    """The live selection cannot become an auditionable private candidate."""


def _canonical_staging(
    producer_dir: str,
    staging_dir: str,
) -> str:
    producer = os.path.realpath(producer_dir)
    lexical = os.path.abspath(staging_dir)
    expected = os.path.join(producer, ".sniper-cut-repair-staging")
    if lexical != staging_dir or not lexical.startswith(expected + os.sep):
        raise PreparationError(
            "cut repair preparation must use controller-owned staging")
    if os.path.realpath(staging_dir) != staging_dir:
        raise PreparationError("cut repair staging directory is not canonical")
    return staging_dir


def _tool(name: str) -> tuple[str, str]:
    found = shutil.which(name)
    if not found:
        raise PreparationError(f"{name} is required for cut repair media")
    executable = os.path.realpath(found)
    return executable, file_sha256(executable)


def _tools() -> RepairMediaTools:
    ffmpeg, ffmpeg_hash = _tool("ffmpeg")
    ffprobe, ffprobe_hash = _tool("ffprobe")
    return RepairMediaTools(
        ffmpeg, ffmpeg_hash, ffprobe, ffprobe_hash).validate()


def _clock(context: dict) -> ProjectClock:
    value = context.get("clock")
    if not isinstance(value, dict):
        raise PreparationError("cut repair context has no project clock")
    sample_rate = value.get("sampleRate")
    if type(sample_rate) is not int or sample_rate <= 0:
        raise PreparationError("cut repair project sample rate is invalid")
    try:
        rate = PositiveRational.from_value(value.get("fps"))
    except (TypeError, ValueError) as exc:
        raise PreparationError("cut repair project FPS is invalid") from exc
    return ProjectClock(rate, sample_rate)


def _selection(result: dict) -> tuple[dict, str, dict, str]:
    selected = result.get("recommendedCandidate")
    if result.get("status") != "eligible" or not isinstance(selected, dict):
        reason = result.get("rippleImpact") or result.get("status")
        raise PreparationError(f"cut repair has no eligible candidate: {reason}")
    operation = selected.get("operation")
    operation_hash = selected.get("operationHash")
    policy = selected.get("selectionPolicy")
    policy_hash = selected.get("selectionPolicyHash")
    if not isinstance(operation, dict) or content_hash(operation) != operation_hash:
        raise PreparationError("selected cut repair operation is stale")
    if not isinstance(policy, dict) or content_hash(policy) != policy_hash:
        raise PreparationError("selected cut repair policy is stale")
    method = operation.get("method")
    if method == "extend-and-reclaim-silence":
        return operation, operation_hash, policy, policy_hash
    if method != "audio-lj-overlap":
        raise PreparationError("PLAN_VOCABULARY_REPAIR_METHOD_UNAVAILABLE")
    segment = operation.get("segment")
    if not isinstance(segment, dict) or segment.get("edge") != "start":
        raise PreparationError("PLAN_VOCABULARY_LCUT_UNAVAILABLE")
    return operation, operation_hash, policy, policy_hash


def _media_row(context: dict, name: str) -> dict:
    value = context.get(name)
    if not isinstance(value, dict) \
            or not isinstance(value.get("path"), str):
        raise PreparationError(f"cut repair context {name} is malformed")
    return value


def _lead_ms(operation: dict, sample_rate: int) -> int:
    try:
        return lead_ms(operation, sample_rate)
    except ValueError as exc:
        raise PreparationError(str(exc)) from exc


def _review_plan(
    producer_dir: str,
    context: dict,
    operation: dict,
    clock: ProjectClock,
) -> tuple[dict, dict]:
    try:
        return review_plan(producer_dir, context, operation, clock)
    except ValueError as exc:
        raise PreparationError(str(exc)) from exc


def _review_plan_result(
    producer_dir: str,
    context: dict,
    operation: dict,
    clock: ProjectClock,
):
    try:
        return review_plan_result(producer_dir, context, operation, clock)
    except ValueError as exc:
        raise PreparationError(str(exc)) from exc


def _clear_unsealed_outputs(staging_dir: str) -> tuple[str, str]:
    fragment = os.path.join(staging_dir, "fragment.mov")
    composite = os.path.join(staging_dir, "candidate.mov")
    for output in (fragment, composite):
        try:
            os.unlink(output)
        except FileNotFoundError:
            pass
    return fragment, composite


def prepare(
    producer_dir: str,
    directive_path: str,
    context_path: str,
    staging_dir: str,
) -> dict:
    """Re-resolve live analysis, then render its exact selected media."""
    staging = _canonical_staging(producer_dir, staging_dir)
    context, _ = stable_json(context_path, "cut repair context")
    result = run(producer_dir, directive_path, context_path)
    operation, operation_hash, policy, policy_hash = _selection(result)
    parent = _media_row(context, "parentMedia")
    source = _media_row(context, "sourceMedia")
    clock = _clock(context)
    planned = _review_plan_result(
        producer_dir, context, operation, clock)
    review_plan, review_projection = planned.plan, planned.projection
    tools = _tools()
    fragment_path, composite_path = _clear_unsealed_outputs(staging)
    fragment = render_repair_fragment(RepairFragmentRequest(
        operation, operation_hash, parent["path"], source["path"],
        fragment_path, clock, tools))
    composite = render_repair_composite(RepairCompositeRequest(
        parent["path"], fragment_path, composite_path, fragment,
        operation_hash, clock, tools))
    return {
        "schemaVersion": 1,
        "kind": "cut-repair-prepared-media",
        "parentRevisionHash": result["parentRevisionHash"],
        "contextAuthorityHash": result["contextAuthorityHash"],
        "operation": operation,
        "operationHash": operation_hash,
        "selectionPolicy": policy,
        "selectionPolicyHash": policy_hash,
        "projectSampleRate": clock.sample_rate,
        "reviewPlan": review_plan,
        "reviewPlanHash": stable_digest(review_plan),
        "reviewProjection": review_projection,
        "reviewTimelineMapHash": review_projection["timelineMapHash"],
        "fragmentReceipt": fragment,
        "compositeReceipt": composite,
    }


def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("producer_dir")
    parser.add_argument("directive_path")
    parser.add_argument("context_path")
    parser.add_argument("staging_dir")
    args = parser.parse_args()
    try:
        value = prepare(
            os.path.abspath(args.producer_dir),
            os.path.abspath(args.directive_path),
            os.path.abspath(args.context_path),
            os.path.abspath(args.staging_dir),
        )
        print(canonical_json(value))
        return 0
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(_main())
