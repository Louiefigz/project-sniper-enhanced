"""Publish an explicit, unselected manifest for one committed timing correction.

The source admission store is anchored to the original manifest directory. Only
the selected source's transcript pointer changes; this command never overwrites
the original manifest or plan, selects a project head, or transfers approval.
Interrupted publication can leave a new file. A later status must revalidate it;
file existence alone is not successful publication or permission to render.
"""
from __future__ import annotations

import argparse
import copy
from dataclasses import replace
import hashlib
import math
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from color.deadline import wall_budget
from cut_preview_io import read_bytes, real_directory, write_new
from transcript_timing_correction import execute as correction_status
from transcript_timing_correction_authority import CorrectionInput
from transcript_timing_correction_contract import MAX_INPUT_BYTES, proposal as parse_proposal
from transcript_timing_review_contract import closed, hash_value, parse_json, record_bytes

WORK_SECONDS = 120
OPERATION = "publish-corrected-transcript-manifest"


def _request(value: object) -> dict:
    """Require the operator's exact committed correction, without inferred intent."""
    keys = {"schemaVersion", "operation", "expectedRequestHash", "expectedRecordHash",
            "expectedCorrectedTranscriptSha256"}
    row = closed(value, keys, "corrected manifest publication")
    if type(row["schemaVersion"]) is not int or row["schemaVersion"] != 1 \
            or row["operation"] != OPERATION:
        raise RuntimeError("unsupported corrected transcript manifest publication")
    for key in keys - {"schemaVersion", "operation"}:
        hash_value(row[key], key)
    return row


def _deadline(inputs: CorrectionInput, started: float) -> float:
    """Use one original command expiry, shortened by any caller-owned deadline."""
    parent = inputs.parent_deadline
    if parent is not None and (type(parent) not in (int, float) or not math.isfinite(parent)):
        raise RuntimeError("corrected manifest caller deadline must be finite")
    deadline = min(started + WORK_SECONDS, parent) if parent is not None else started + WORK_SECONDS
    _guard(deadline)
    return deadline


def _guard(deadline: float) -> None:
    """Fail closed without starting a fresh command budget after a slow phase."""
    if time.monotonic() >= deadline:
        raise RuntimeError("corrected manifest exceeded its original 120-second work budget")


def _committed(inputs: CorrectionInput, proposed: dict, sent: dict) -> dict:
    """Use the full correction reader, not a self-hash or file-existence shortcut."""
    result = correction_status("status", inputs, proposed)
    revision = result.get("revision")
    if result.get("ok") is not True or result.get("state") != "committed" or type(revision) is not dict:
        raise RuntimeError("corrected manifest requires a committed, freshly verified correction")
    if result["request"]["requestHash"] != sent["expectedRequestHash"] \
            or revision["recordHash"] != sent["expectedRecordHash"] \
            or revision["sha256"] != sent["expectedCorrectedTranscriptSha256"]:
        raise RuntimeError("corrected manifest expected correction bindings changed")
    return {"request": result["request"], "revision": revision}


def _manifest(inputs: CorrectionInput, proposed: dict, verified: dict) -> tuple[Path, dict]:
    """Retain source-set paths and every original field except one transcript path."""
    parent = inputs.manifest_path.parent
    real_directory(parent)
    original = read_bytes(inputs.manifest_path, MAX_INPUT_BYTES)
    if hashlib.sha256(original).hexdigest() != proposed["expectedManifestSha256"]:
        raise RuntimeError("corrected manifest original bytes changed")
    manifest = parse_json(original)
    if type(manifest) is not dict or type(manifest.get("sources")) is not list:
        raise RuntimeError("corrected manifest original source list is invalid")
    relative = Path(".sniper-timing-corrections") / proposed["requestId"] / "corrected-transcript.json"
    transcript = parent / relative
    if verified["revision"]["path"] != str(transcript):
        raise RuntimeError("corrected transcript is not in its committed source directory")
    raw = read_bytes(transcript, MAX_INPUT_BYTES)
    if hashlib.sha256(raw).hexdigest() != verified["revision"]["sha256"]:
        raise RuntimeError("corrected transcript bytes changed before manifest publication")
    result = copy.deepcopy(manifest)
    matches = [row for row in result["sources"] if type(row) is dict and row.get("id") == proposed["sourceId"]]
    if len(matches) != 1:
        raise RuntimeError("corrected manifest source does not resolve uniquely")
    matches[0]["transcriptPath"] = relative.as_posix()
    target = parent / f"asset_manifest.timing-{proposed['requestId']}.json"
    if target == inputs.manifest_path:
        raise RuntimeError("corrected manifest cannot overwrite its original parent")
    record_bytes(result)
    return target, result


def _observe(path: Path, expected: bytes) -> bool:
    """Exact read-only replay; a partial or conflicting existing file is terminal."""
    if not os.path.lexists(path):
        return False
    if read_bytes(path, MAX_INPUT_BYTES) != expected:
        raise RuntimeError("corrected manifest publication conflicts with retained bytes")
    return True


def _publish(command: str, path: Path, value: dict) -> tuple[bool, bool]:
    """Create only the derived new path; concurrent identical writers may replay."""
    expected = record_bytes(value)
    existed = _observe(path, expected)
    if command == "status" or existed:
        return existed, existed
    try:
        write_new(path, value)
    except FileExistsError:
        if not _observe(path, expected):
            raise RuntimeError("corrected manifest concurrent publication disappeared")
        return True, True
    if not _observe(path, expected):
        raise RuntimeError("corrected manifest disappeared after creation")
    return True, False


def execute(command: str, inputs: CorrectionInput, proposed: object, publication: object) -> dict:
    """Publish/status a fresh-manifest option; explicitly selecting it is separate."""
    started = time.monotonic()
    deadline = _deadline(inputs, started)
    if command not in {"publish", "status"}:
        raise RuntimeError("unknown corrected manifest command")
    with wall_budget(deadline):
        proposed, sent = parse_proposal(proposed), _request(publication)
    held = replace(inputs, parent_deadline=deadline)
    verified = _committed(held, proposed, sent)
    with wall_budget(deadline):
        path, value = _manifest(held, proposed, verified)
        published, replayed = _publish(command, path, value)
    after = _committed(held, proposed, sent)  # Same expiry; no nested wall timers.
    with wall_budget(deadline):
        if after != verified:
            raise RuntimeError("corrected manifest correction authority changed during publication")
        current_path, current = _manifest(held, proposed, after)
        if current_path != path or record_bytes(current) != record_bytes(value) \
                or _observe(path, record_bytes(value)) != published:
            raise RuntimeError("corrected manifest changed during final observation")
        result = {"ok": True, "command": command, "state": "published" if published else "not-published",
                  "manifestPath": str(path), "manifestSha256": hashlib.sha256(record_bytes(value)).hexdigest(),
                  "transcriptsDir": str(held.manifest_path.parent), "requestHash": sent["expectedRequestHash"],
                  "recordHash": sent["expectedRecordHash"], "replayed": replayed,
                  "sourceFreshness": "actual-admitted-bytes-observed-before-and-after-publication",
                  "freshCutRevisionRequired": True, "newPlanWritten": False, "selected": False,
                  "approvalsTransferred": False, "subjectiveListening": "not-performed-by-system",
                  "deliveryApproved": False, "elapsedMs": round((time.monotonic() - started) * 1000, 3)}
        _guard(deadline)
        return result


def _load(path: str) -> object:
    """Read one small exact JSON input; attached text cannot select the command."""
    return parse_json(read_bytes(Path(os.path.abspath(path)), MAX_INPUT_BYTES))


def main() -> int:
    """Expose explicit local publication without automatic bootstrap or approval."""
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("command", choices=("publish", "status"))
    for name in ("plan", "manifest", "transcript", "proposal", "publication"):
        parser.add_argument(name)
    args = parser.parse_args()
    try:
        started = time.monotonic()
        with wall_budget(started + WORK_SECONDS):
            inputs = CorrectionInput(*(Path(os.path.abspath(getattr(args, key)))
                                       for key in ("plan", "manifest", "transcript")),
                                     parent_deadline=started + WORK_SECONDS)
            proposed, sent = _load(args.proposal), _load(args.publication)
        result = execute(args.command, inputs, proposed, sent)
        with wall_budget(inputs.parent_deadline):
            result["elapsedMs"] = round((time.monotonic() - started) * 1000, 3)
            print(record_bytes(result).decode("utf-8"), end="", flush=True)
        return 0
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
        print(record_bytes({"ok": False, "error": str(exc)[:1000],
                            "manifestMayHaveBeenWritten": args.command == "publish",
                            "selected": False, "approvalsTransferred": False, "deliveryApproved": False})
              .decode("utf-8"), end="")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
