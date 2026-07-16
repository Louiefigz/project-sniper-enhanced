"""Evidence-only learning observations from critics, QC, and Palmier drift."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Mapping

from learning.doctrine_lifecycle import DoctrineLifecycleError, DoctrineLock

_SHA = re.compile(r"^[0-9a-f]{64}$")
_RUNTIME_ROOT_KEYS = {"canGenerate", "currentFrame", "timelines"}


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class LearningObservation:
    """An immutable fact record; it has no authority to edit doctrine."""

    observation_id: str
    run_id: str
    doctrine_hash: str
    source_kind: str
    code: str
    lane: str
    severity: str
    evidence_json: str
    observation_hash: str

    @property
    def evidence(self) -> dict:
        """Return a fresh evidence object so callers cannot mutate the record."""
        return json.loads(self.evidence_json)

    def receipt(self) -> dict:
        """Return a JSON-safe observation receipt."""
        return {
            "schemaVersion": 1, "status": "observed",
            "observationId": self.observation_id, "runId": self.run_id,
            "doctrineHash": self.doctrine_hash, "sourceKind": self.source_kind,
            "code": self.code, "lane": self.lane, "severity": self.severity,
            "evidence": self.evidence, "observationHash": self.observation_hash,
        }


def _observation(lock: DoctrineLock, observation_id: str,
                 source: Mapping[str, object], evidence: dict) -> LearningObservation:
    required = ("kind", "code", "lane", "severity")
    if not observation_id or any(not isinstance(source.get(key), str)
                                 or not source.get(key) for key in required):
        raise DoctrineLifecycleError("observation identity fields cannot be empty")
    evidence_json = _canonical(evidence)
    core = {
        "schemaVersion": 1, "observationId": observation_id,
        "runId": lock.run_id, "doctrineHash": lock.doctrine_hash,
        "sourceKind": source["kind"], "code": source["code"],
        "lane": source["lane"], "severity": source["severity"],
        "evidence": json.loads(evidence_json),
    }
    return LearningObservation(observation_id, lock.run_id, lock.doctrine_hash,
                               str(source["kind"]), str(source["code"]),
                               str(source["lane"]), str(source["severity"]),
                               evidence_json, _hash(core))


def _artifact(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise DoctrineLifecycleError(f"{label} must be a SHA-256 artifact hash")
    return value


def critic_observation(lock: DoctrineLock, observation_id: str,
                       issue: Mapping[str, object]) -> LearningObservation:
    """Record one explicit scoped critic issue; do not synthesize a lesson."""
    if issue.get("severity") not in ("major", "critical"):
        raise DoctrineLifecycleError("only material critic issues teach the loop")
    evidence = issue.get("evidence")
    if not isinstance(evidence, list) or not evidence \
            or any(not isinstance(item, str) or not item for item in evidence):
        raise DoctrineLifecycleError("critic observation needs concrete evidence")
    source = {"kind": "critic", "code": issue.get("code"),
              "lane": issue.get("lane"), "severity": issue.get("severity")}
    payload = {"reviewArtifactHash": _artifact(issue.get("reviewArtifactHash"),
                                                "critic review"),
               "evidence": list(evidence)}
    return _observation(lock, observation_id, source, payload)


def qc_observation(lock: DoctrineLock, observation_id: str,
                   finding: Mapping[str, object]) -> LearningObservation:
    """Record one deterministic QC warning/failure and its receipt hash."""
    if finding.get("status") not in ("warn", "fail"):
        raise DoctrineLifecycleError("only QC warnings and failures teach the loop")
    source = {"kind": "qc", "code": finding.get("code"),
              "lane": finding.get("lane"),
              "severity": "critical" if finding.get("status") == "fail" else "major"}
    payload = {"qcArtifactHash": _artifact(finding.get("qcArtifactHash"), "QC"),
               "status": finding["status"], "measurement": finding.get("measurement")}
    return _observation(lock, observation_id, source, payload)


def _pointer(path: str, key: object) -> str:
    token = str(key).replace("~", "~0").replace("/", "~1")
    return f"{path}/{token}"


def _diff(before: object, after: object, path: str = "") -> list[dict]:
    if type(before) is not type(after):
        return [{"op": "replace", "path": path or "/",
                 "beforeHash": _hash(before), "afterHash": _hash(after)}]
    if isinstance(before, dict):
        rows = []
        for key in sorted(set(before) | set(after)):
            at = _pointer(path, key)
            if key not in before:
                rows.append({"op": "add", "path": at, "afterHash": _hash(after[key])})
            elif key not in after:
                rows.append({"op": "remove", "path": at,
                             "beforeHash": _hash(before[key])})
            else:
                rows.extend(_diff(before[key], after[key], at))
        return rows
    if isinstance(before, list):
        rows = []
        for index in range(max(len(before), len(after))):
            at = _pointer(path, index)
            if index >= len(before):
                rows.append({"op": "add", "path": at, "afterHash": _hash(after[index])})
            elif index >= len(after):
                rows.append({"op": "remove", "path": at,
                             "beforeHash": _hash(before[index])})
            else:
                rows.extend(_diff(before[index], after[index], at))
        return rows
    if before == after:
        return []
    return [{"op": "replace", "path": path or "/",
             "beforeHash": _hash(before), "afterHash": _hash(after)}]


def _timeline(record: object, label: str) -> tuple[dict, dict]:
    if not isinstance(record, dict) or not isinstance(record.get("timeline"), dict):
        raise DoctrineLifecycleError(f"manual diff {label} timeline is missing")
    content = {key: value for key, value in record["timeline"].items()
               if key not in _RUNTIME_ROOT_KEYS}
    fingerprint = record.get("fingerprint")
    if fingerprint != _hash(content):
        raise DoctrineLifecycleError(f"manual diff {label} fingerprint is stale")
    authority = {"timelineId": record.get("timelineId"),
                 "projectId": record.get("projectId"),
                 "fingerprint": fingerprint,
                 "semanticFingerprint": record.get("semanticFingerprint")}
    if not isinstance(authority["timelineId"], str) or not authority["timelineId"]:
        raise DoctrineLifecycleError(f"manual diff {label} timeline id is missing")
    if not isinstance(authority["projectId"], str) or not authority["projectId"]:
        raise DoctrineLifecycleError(f"manual diff {label} project id is missing")
    return content, authority


def manual_timeline_observation(lock: DoctrineLock, observation_id: str,
                                revision: Mapping[str, object]) -> LearningObservation:
    """Record hashed Palmier before/after paths without inferring intent or taste."""
    before, before_auth = _timeline(revision.get("before"), "before")
    after, after_auth = _timeline(revision.get("after"), "after")
    if before_auth["projectId"] != after_auth["projectId"]:
        raise DoctrineLifecycleError("manual diff crosses Palmier projects")
    changes = _diff(before, after)
    if not changes or before_auth["fingerprint"] == after_auth["fingerprint"]:
        raise DoctrineLifecycleError("manual Palmier observation has no content change")
    diff = {"changeCount": len(changes), "changes": changes}
    diff["digest"] = _hash(diff)
    source = {"kind": "palmier-manual", "code": "PALMIER_MANUAL_REVISION",
              "lane": str(revision.get("lane") or "timeline"), "severity": "info"}
    payload = {"before": before_auth, "after": after_auth, "diff": diff,
               "interpretation": "none"}
    return _observation(lock, observation_id, source, payload)
