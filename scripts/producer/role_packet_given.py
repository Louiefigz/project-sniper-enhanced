"""The subject's given (approved) title and script, read only from the batch authority.

Requirement revision `approved-content-production-2026-09-27`: titles and scripts are handed over
at batch start and bound in the batch authority (unit A1/A2), the only source of them and, through
its typed approval-changed events, the only record of a change. A packet names the batch and clip
explicitly (`--batch`/`--clip`); whenever a live batch holds the plan's source recording, omitting
them is refused, so an approval can never be skipped. The reader is A1/A2's
`studio.production.api.read_approval(root, batch, clip)` on the per-user authority root
(`native_budget_store.default_root()`); there is no other source and no stand-in (unit tests patch
`authority.read_approval` with a TEST reader). The plan's source and cut selection must be that
clip's Short by the authority's own selection arithmetic (`studio.native_budget_selection.same_short`).
`read_as_submitted` is the read-only reading of an existing record (`check-final`): the approval in force
at the record's recorded submission, walking the chain's `previous` links, whatever the batch's status now.

`given` (the packet contract other units read) is either {"status": "not-supplied", "meaning"} or
{"status": "bound", "readFrom", "requirementRevision", "batchId", "clipId", "authorityStatus",
"identity", "scriptSha256", "titleSha256", "planChecked", "title", "selection", "captionText",
"timing"}: title {given, planned, status: exact|normalization-only|different, material} and
selection/captionText/timing {matches, details} (role_packet_speech; None without a plan).
"""
from __future__ import annotations

from dataclasses import dataclass

from role_packet_approvals import CANONICAL_FORM, ApprovalError, verified_row
from role_packet_evidence_record import observed_inputs, source_transcript
from role_packet_native import request_value
from role_packet_speech import comparison, plan_selection, planned_source
from role_packet_transcript import Transcript
from studio.native_budget_batches import current_batches, live_records
from studio import native_budget_store
from studio.production import api as authority
from studio.native_budget_selection import merged, same_short
from studio.native_budget_store import require_batch_id, require_clip_id

READER = "studio.production.api"  # the module `authority` names; recorded as the block's readFrom
REVISION = "approved-content-production-2026-09-27"
FORM = CANONICAL_FORM.split(":", 1)[0] + ":"
NOT_SUPPLIED = {"status": "not-supplied", "meaning": "No live batch holds this plan's source recording; no given title "
                "or script applies. This is not a refusal of any approval."}


@dataclass(frozen=True)
class GivenRequest:
    """The batch and clip a packet names (both or neither)."""
    batch: str | None
    clip: str | None


def clip_holdings(batch_id: str, record: dict, selection: dict) -> list[dict]:
    """This batch's hold on the plan's recording: a declared source claim, bound projects or approvals on it."""
    rows = []
    for clip_id, clip in record["clips"].items():
        held = [row["selection"] for row in clip.get("projects") or []]
        held += [{"source": row["source"], "ranges": merged(row["ranges"])} for row in clip.get("approvals") or []]
        on_source = [item for item in held if item["source"] == selection["source"]]
        rows += [{"batchId": batch_id, "clipId": clip_id,
                  "sameShort": any(same_short(item, selection) for item in on_source)}] if on_source else []
    claimed = selection["source"] in (record.get("claims") or [])
    return rows or ([{"batchId": batch_id, "clipId": "*", "sameShort": False}] if claimed else [])


def refuse_omission(selection: dict) -> None:
    """Refuse a packet that names no batch while a live batch claims or holds this plan's source recording."""
    holdings = [row for batch_id, record in live_records(native_budget_store.default_root())
                for row in clip_holdings(batch_id, record, selection)]
    if holdings:
        likely = [f"{row['batchId']}/{row['clipId']}" for row in holdings if row["sameShort"]] or \
                 [f"{row['batchId']}/{row['clipId']}" for row in holdings]
        raise ApprovalError(f"a live batch holds this plan's source recording ({likely[:6]}); name its approved title "
                            "and script with --batch <id> --clip <id>")


def require_current_batch(root, batch: str) -> None:
    """Only the one active or draining batch binds given content; a closed or archived batch never does."""
    current = [name for name, _record in current_batches(root)]
    if current != [batch]:
        raise ApprovalError(f"batch {batch} is not the current active or draining batch ({current or 'none is'}); "
                            "a closed, archived or superseded batch's approval binds nothing")


def read_current(request: GivenRequest) -> dict:
    """The current batch's current approval for the named clip, or a specific refusal."""
    batch, clip = require_batch_id(request.batch), require_clip_id(request.clip)
    root = native_budget_store.default_root()
    require_current_batch(root, batch)
    found = authority.read_approval(root, batch, clip)
    if not isinstance(found, dict) or found.get("current") is None:
        raise ApprovalError(f"batch {batch} clip {clip} has no approved title/script")
    if found.get("status") not in ("active", "draining"):
        raise ApprovalError(f"batch {batch} is {found.get('status')}; only an active or draining batch binds given content")
    if not str(found.get("canonicalForm", "")).startswith(FORM):
        raise ApprovalError(f"batch {batch} clip {clip}'s approval is not in {FORM[:-1]} form")
    return {**found, "batchId": batch, "clipId": clip}


def approval_in_force(history: list[dict], elapsed: float) -> tuple[dict, dict]:
    """The approval row in force at a batch-clock time and the chain's latest row, walking A12's ``previous`` links."""
    previous, since = None, 0.0
    for row in history:
        if row.get("previous") != previous or row["elapsed"] < since:
            raise ApprovalError("the clip's approval chain is broken: a row does not name its predecessor in time order")
        previous, since = row["identity"], row["elapsed"]
    in_force = [row for row in history if row["elapsed"] <= elapsed]
    if not in_force:
        raise ApprovalError(f"no approved title and script was in force at {elapsed} s of the batch clock")
    return in_force[-1], history[-1]


def read_as_submitted(request: GivenRequest, elapsed: float) -> tuple[dict, dict]:
    """The named clip's approval in force at a record's recorded submission (any batch status, live or archived) and
    what the record was read against: that approval, the batch status now and any later approval superseding it."""
    batch, clip = require_batch_id(request.batch), require_clip_id(request.clip)
    found = authority.read_approval(native_budget_store.default_root(), batch, clip)
    if not isinstance(found, dict) or not found.get("history"):
        raise ApprovalError(f"batch {batch} clip {clip} has no approved title/script")
    if not str(found.get("canonicalForm", "")).startswith(FORM):
        raise ApprovalError(f"batch {batch} clip {clip}'s approval is not in {FORM[:-1]} form")
    row, latest = approval_in_force(found["history"], elapsed)
    later = None if latest["identity"] == row["identity"] else {"identity": latest["identity"], "elapsed": latest["elapsed"]}
    reading = {"submittedElapsed": elapsed, "authorityStatus": found.get("status"), "approvalIdentity": row["identity"],
               "approvalElapsed": row["elapsed"], "supersededBy": later}
    return {**found, "batchId": batch, "clipId": clip, "current": row}, reading


def plan_transcript(plan: dict) -> Transcript:
    """The admitted transcript of the plan's own source recording, through its request packet's manifest."""
    manifest = (request_value(plan) or {}).get("manifest")
    if not isinstance(manifest, dict) or not isinstance(manifest.get("path"), str):
        raise ApprovalError("cannot compare the given script: this plan binds no request packet with an admitted manifest")
    inputs = observed_inputs(manifest["path"], [])
    source = next((row["id"] for row in inputs["sources"] if row["sourceSha256"] == planned_source(plan)), None)
    if source is None:
        raise ApprovalError("this plan's source recording is not in its admitted manifest")
    return source_transcript(inputs, source)[1]


def bound_facts(found: dict, plan: dict | None) -> dict:
    """The packet's `given` block for a verified authority approval."""
    current = found["current"]
    header = {"status": "bound", "readFrom": f"{READER}.read_approval", "requirementRevision": REVISION,
              "batchId": found["batchId"], "clipId": found["clipId"], "authorityStatus": found.get("status"),
              "identity": current.get("identity"), "scriptSha256": current.get("script"),
              "titleSha256": current.get("titleSha256")}
    if plan is None:
        return {**header, "planChecked": False, "title": {"given": current.get("title")}, "selection": None,
                "captionText": None, "timing": None}
    selection = plan_selection(plan)
    if selection is None or not same_short(selection, {"source": current["source"], "ranges": merged(current["ranges"])}):
        raise ApprovalError(f"this plan's source and cut selection are not batch {found['batchId']} clip "
                            f"{found['clipId']}'s Short (the authority's selection arithmetic)")
    transcript = plan_transcript(plan)
    return {**header, "planChecked": True, **comparison(verified_row(current, transcript, derived_seconds=False),
                                                         plan, transcript)}


def resolve_given(request: GivenRequest, plan: dict | None) -> dict:
    """Bind the named clip's approval, or state that none applies; never silently omit one."""
    if (request.batch is None) != (request.clip is None):
        raise ApprovalError("--batch and --clip name one clip together")
    if request.batch is None:
        selection = plan_selection(plan) if plan is not None else None
        if selection is not None:
            refuse_omission(selection)
        return dict(NOT_SUPPLIED)
    return bound_facts(read_current(request), plan)
