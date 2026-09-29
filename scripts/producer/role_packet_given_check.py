"""Re-check a role packet's given block against the batch authority: ``context.py --given-check <packet>``.

Requirement revision `approved-content-production-2026-09-27`, gate side. A typed review record answers one
hash-bound role packet whose ``given`` block was true when the packet was resolved. Since then the operator may
have changed the approved title or script, a batch may have started that holds the plan's source, or the block
may have been edited or copied from another packet. The submission and every gate that admits a build, a full
render or an export re-run this check: a bound block is re-resolved from the authority's CURRENT approval for its
batch and clip against the plan the packet froze (``resolve_given``; the batch must still be the current active or
draining batch), and a not-supplied or absent block re-runs the omission refusal, so a live batch that now holds
the plan's source refuses it. The TypeScript readers then require the record's approved content to equal what this
fresh block yields. For a bound packet the report also carries its batch-clock resolution and, for an existing
record (``--record-sha256``), the ``review-submitted`` event the submission recorded (``studio.production.packets``).

``--as-submitted`` is the read-only verification of an existing record (``native-review.ts check-final``): the
block is re-resolved from the approval that was in force at the record's recorded submission time, walking A12's
approval chain (``previous``), in any batch status, so a record still verifies after its batch closed or was
archived. The report names the approval in force then and any later approval that superseded it; it never admits
new work. ``--review-submitted <packet>`` records the submission event itself (the typed submission calls it).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from role_packet_approvals import ApprovalError
from role_packet_files import ArtifactError, canonical_file, read_json
from role_packet_given import GivenRequest, bound_facts, read_as_submitted, resolve_given
from studio import native_budget_store
from studio.production.packets import (
    ResolvedPacket, SubmittedReview, packet_resolution, record_packet_resolved, record_review_submitted, review_submission,
)

REPORT = "given-current"
CRITICS = ("plan-critic", "motion-critic", "final-critic")
MAX_PACKET_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True)
class CheckRequest:
    """What a caller re-checks: one packet and, for an existing record, its canonical SHA-256 and reading."""
    packet_file: str
    record_sha256: str | None = None
    as_submitted: bool = False


def frozen_plan(packet: dict) -> dict | None:
    """The plan the packet reviewed (a plan file, or the reviewed project's SHORT-PROJECT.json), unchanged since."""
    subject = packet.get("subject") if isinstance(packet.get("subject"), dict) else {}
    plan = subject.get("plan") if isinstance(subject.get("plan"), dict) else {}
    named = plan.get("path") if isinstance(plan.get("path"), str) else None
    if named is None and isinstance(subject.get("project"), str):
        named = str(Path(subject["project"]) / "SHORT-PROJECT.json")
    if named is None:
        return None
    file = canonical_file(named)
    frozen = [row.get("sha256") for row in packet.get("artifacts") or [] if row.get("path") == str(file)]
    if frozen != [hashlib.sha256(file.read_bytes()).hexdigest()]:
        raise ApprovalError(f"the plan this packet reviewed ({file}) changed since the packet froze it, or the packet "
                            "does not freeze it")
    return read_json(file)


def read_packet(packet_file: str) -> tuple[Path, dict, str]:
    """The packet file, its JSON and the SHA-256 of its exact bytes."""
    file = canonical_file(packet_file)
    if file.stat().st_size > MAX_PACKET_BYTES:
        raise ArtifactError(f"{file} exceeds the role packet size bound")
    raw = file.read_bytes()
    packet = json.loads(raw)
    if not isinstance(packet, dict) or packet.get("kind") != "sniper-role-packet":
        raise ArtifactError(f"{file} is not a role packet")
    return file, packet, hashlib.sha256(raw).hexdigest()


def named_clip(packet: dict) -> GivenRequest | None:
    """The batch clip a bound given block names, or None for a not-supplied or absent block."""
    given = packet.get("given")
    if isinstance(given, dict) and given.get("status") == "bound":
        return GivenRequest(given.get("batchId"), given.get("clipId"))
    return None


def resolution(packet: dict, sha256: str, request: GivenRequest) -> dict:
    """The batch clock at which the authority recorded this exact packet, and the batch clock now."""
    found = packet_resolution(native_budget_store.default_root(), request.batch, sha256)
    if (found["clipId"], found["role"]) != (request.clip, packet.get("role")):
        raise ApprovalError(f"batch {request.batch} recorded packet {sha256[:12]} for {found['role']} on clip "
                            f"{found['clipId']}, not this packet's role and clip")
    return {"batchId": request.batch, "clipId": request.clip, "resolvedElapsed": found["resolvedElapsed"],
            "nowElapsed": found["nowElapsed"]}


def bound_check(request: CheckRequest, named: GivenRequest, plan: dict | None) -> dict:
    """A bound block re-resolved now (admitting gates) or as of the record's recorded submission (check-final)."""
    root = native_budget_store.default_root()
    submitted = review_submission(root, named.batch, request.record_sha256) if request.record_sha256 else None
    if not request.as_submitted:
        return {"given": resolve_given(named, plan), "submitted": submitted, "asSubmitted": None}
    if submitted is None:
        raise ApprovalError("--as-submitted verifies an existing record: name it with --record-sha256")
    found, as_of = read_as_submitted(named, submitted["elapsed"])
    return {"given": bound_facts(found, plan), "submitted": submitted, "asSubmitted": as_of}


def given_check(request: CheckRequest) -> dict:
    """The packet's given block as the authority and the reviewed plan yield it, plus its batch-clock events."""
    file, packet, sha256 = read_packet(request.packet_file)
    plan = frozen_plan(packet)
    if plan is None and packet.get("role") in CRITICS:
        raise ApprovalError(f"{file} is a {packet.get('role')} packet that freezes no reviewed plan; its approved content "
                            "cannot be re-checked")
    named = named_clip(packet)
    if named is None:
        fresh = {"given": resolve_given(GivenRequest(None, None), plan), "submitted": None, "asSubmitted": None}
        return {"status": REPORT, "packet": {"path": str(file), "sha256": sha256}, **fresh, "batchClock": None}
    fresh = bound_check(request, named, plan)
    return {"status": REPORT, "packet": {"path": str(file), "sha256": sha256}, **fresh,
            "batchClock": resolution(packet, sha256, named)}


def record_resolution(packet: dict, sha256: str) -> dict | None:
    """Record a batch-bound packet's resolution on the batch clock before the packet is published."""
    named = named_clip(packet)
    if named is None:
        return None
    event = record_packet_resolved(native_budget_store.default_root(),
                                   ResolvedPacket(named.batch, named.clip, packet["role"], sha256))
    return {"batchId": named.batch, "clipId": named.clip, "resolvedElapsed": event["elapsed"]}


def record_submission(packet_file: str, record_sha256: str, elapsed: float) -> dict:
    """Record a batch-bound record's submission on its batch clock (the typed submission calls this)."""
    file, packet, sha256 = read_packet(packet_file)
    named = named_clip(packet)
    if named is None:
        raise ApprovalError(f"{file} binds no batch clip; only a batch-bound review is recorded on a batch clock")
    review = SubmittedReview(ResolvedPacket(named.batch, named.clip, packet.get("role"), sha256), record_sha256, elapsed)
    event = record_review_submitted(native_budget_store.default_root(), review)
    return {"status": "review-submitted-recorded", "packet": {"path": str(file), "sha256": sha256}, "event": event}


def given_arguments(parser: argparse.ArgumentParser) -> None:
    """context.py flags for the gate-time re-check and the submission event."""
    parser.add_argument("--given-check", metavar="PACKET",
                        help="Re-check a role packet's given title/script against the batch authority (gates call it)")
    parser.add_argument("--record-sha256", help="With --given-check/--review-submitted: the record's canonical SHA-256")
    parser.add_argument("--as-submitted", action="store_true",
                        help="With --given-check: verify an existing record as of its recorded submission (read only)")
    parser.add_argument("--review-submitted", metavar="PACKET",
                        help="Record a typed record's submission on its batch clock (the typed submission calls it)")
    parser.add_argument("--submitted-elapsed", type=float, help="With --review-submitted: the record's batch-clock time")


def run(args: argparse.Namespace) -> dict:
    """The one operation the flags name."""
    if args.review_submitted:
        if args.record_sha256 is None or args.submitted_elapsed is None or args.given_check or args.as_submitted:
            raise ApprovalError("--review-submitted takes --record-sha256 and --submitted-elapsed only")
        return record_submission(args.review_submitted, args.record_sha256, args.submitted_elapsed)
    if args.submitted_elapsed is not None or (args.as_submitted and args.record_sha256 is None):
        raise ApprovalError("--given-check takes --record-sha256, and --as-submitted only with it")
    return given_check(CheckRequest(args.given_check, args.record_sha256, args.as_submitted))


def given_main(args: argparse.Namespace) -> int:
    """Print the report; 2 with a bounded error when it cannot be derived or recorded."""
    try:
        result = run(args)
    except (ArtifactError, OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        print(json.dumps({"status": "given-unavailable", "errorType": type(error).__name__,
                          "error": str(error)[:2048]}), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0
