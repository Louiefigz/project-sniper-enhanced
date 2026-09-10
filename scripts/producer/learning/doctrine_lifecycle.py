"""Immutable doctrine locks and explicit next-run promotion boundaries.

It performs no I/O. A controller persists each ``DoctrineLock`` and its exact
UTF-8 text. Observations and proposals stay inert until tests, evals, and an
operator approval authorize a different lock for a different run id.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from cross_runtime_canonical_json import canonical_compact_json

_SHA = re.compile(r"^[0-9a-f]{64}$")
PRODUCER_CORE_DOCTRINE_PATHS = (
    ".agents/skills/producer/SKILL.md",
    ".claude/skills/producer/SKILL.md",
    "docs/PIPELINE.md",
    "scripts/producer/docs/findings/FAILURE_LEDGER.md",
    "scripts/producer/docs/findings/QC_CHECKLIST.md",
)

class DoctrineLifecycleError(ValueError):
    """A doctrine artifact or state transition violates the lifecycle."""

def _canonical(value: object) -> str:
    return canonical_compact_json(value)

def _hash(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()

@dataclass(frozen=True)
class DoctrineFile:
    """One exact doctrine input captured for a run."""
    path: str
    digest: str
    content: str

    def receipt(self) -> dict:
        """Return the hash-only part used to derive doctrine authority."""
        return {"path": self.path, "hash": self.digest}

@dataclass(frozen=True)
class DoctrineLock:
    """The immutable doctrine authority for exactly one edit run."""
    run_id: str
    doctrine_hash: str
    files: tuple[DoctrineFile, ...]
    activation_kind: str = "repository-baseline"
    previous_doctrine_hash: str | None = None
    rollback_doctrine_hash: str | None = None
    proposal_ids: tuple[str, ...] = ()
    activation_evidence_hash: str | None = None

    def text(self, path: str) -> str:
        """Read pinned text; never fall through to a live repository file."""
        for item in self.files:
            if item.path == path:
                return item.content
        raise DoctrineLifecycleError(f"doctrine lock has no {path!r}")

    def receipt(self) -> dict:
        """Return a JSON-safe immutable-run receipt."""
        value = {
            "schemaVersion": 1, "state": "pinned", "runId": self.run_id,
            "doctrineHash": self.doctrine_hash,
            "files": [item.receipt() for item in self.files],
            "activation": {
                "kind": self.activation_kind,
                "previousDoctrineHash": self.previous_doctrine_hash,
                "rollbackDoctrineHash": self.rollback_doctrine_hash,
                "proposalIds": list(self.proposal_ids),
                "evidenceHash": self.activation_evidence_hash,
            },
        }
        value["lockHash"] = _hash(value)
        return value

    def snapshot(self) -> dict:
        """Return the resumable lock, including the exact pinned doctrine text."""
        value = self.receipt()
        value["files"] = [{**item.receipt(), "content": item.content}
                          for item in self.files]
        return value

@dataclass(frozen=True)
class LessonProposal:
    """An inert lesson draft grounded in recorded observations."""
    proposal_id: str
    base_doctrine_hash: str
    observation_ids: tuple[str, ...]
    lesson_text: str
    target_path: str
    author_kind: str
    status: str = "proposed"

@dataclass(frozen=True)
class DoctrineCandidate:
    """Exact proposed doctrine bytes, not active doctrine."""
    base_doctrine_hash: str
    candidate_doctrine_hash: str
    files: tuple[DoctrineFile, ...]
    proposal_ids: tuple[str, ...]
    status: str = "candidate"

def _files(sources: Mapping[str, str]) -> tuple[DoctrineFile, ...]:
    if not sources:
        raise DoctrineLifecycleError("doctrine sources cannot be empty")
    result = []
    for path, content in sorted(sources.items()):
        if not isinstance(path, str) or not path or path.startswith("/"):
            raise DoctrineLifecycleError("doctrine paths must be non-empty and relative")
        if not isinstance(content, str):
            raise DoctrineLifecycleError(f"doctrine source {path!r} is not UTF-8 text")
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        result.append(DoctrineFile(path, digest, content))
    return tuple(result)

def _doctrine_hash(files: Iterable[DoctrineFile]) -> str:
    authority = {"schemaVersion": 1,
                 "files": [item.receipt() for item in files]}
    return _hash(authority)

def capture_run(run_id: str, sources: Mapping[str, str]) -> DoctrineLock:
    """Pin exact doctrine text for a run before any writer or critic starts."""
    if not isinstance(run_id, str) or not run_id:
        raise DoctrineLifecycleError("run id cannot be empty")
    files = _files(sources)
    return DoctrineLock(run_id, _doctrine_hash(files), files)

def capture_producer_run(run_id: str,
                         sources: Mapping[str, str]) -> DoctrineLock:
    """Pin Producer's minimum shared doctrine plus any resolved lane documents."""
    missing = [path for path in PRODUCER_CORE_DOCTRINE_PATHS if path not in sources]
    if missing:
        raise DoctrineLifecycleError(f"Producer doctrine sources missing: {missing}")
    return capture_run(run_id, sources)

def restore_lock(value: Mapping[str, object]) -> DoctrineLock:
    """Restore a persisted snapshot only when all text and hashes still agree."""
    rows = value.get("files")
    activation = value.get("activation")
    if value.get("schemaVersion") != 1 or value.get("state") != "pinned" \
            or not isinstance(rows, list) or not isinstance(activation, dict):
        raise DoctrineLifecycleError("doctrine snapshot has an invalid envelope")
    sources = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("path"), str) \
                or not isinstance(row.get("content"), str):
            raise DoctrineLifecycleError("doctrine snapshot file is malformed")
        digest = hashlib.sha256(row["content"].encode("utf-8")).hexdigest()
        if digest != row.get("hash") or row["path"] in sources:
            raise DoctrineLifecycleError("doctrine snapshot content was changed")
        sources[row["path"]] = row["content"]
    kind = activation.get("kind")
    proposal_ids = activation.get("proposalIds")
    hashes = (activation.get("previousDoctrineHash"),
              activation.get("rollbackDoctrineHash"),
              activation.get("evidenceHash"))
    valid_activation = (kind in ("repository-baseline", "promotion", "rollback")
                        and isinstance(proposal_ids, list)
                        and all(isinstance(item, str) for item in proposal_ids)
                        and all(item is None or (isinstance(item, str)
                                                and _SHA.fullmatch(item))
                                for item in hashes)
                        and ((kind == "repository-baseline" and not any(hashes)
                              and not proposal_ids)
                             or (kind == "promotion" and all(hashes) and proposal_ids)
                             or (kind == "rollback" and all(hashes) and not proposal_ids)))
    if not valid_activation:
        raise DoctrineLifecycleError("doctrine snapshot activation is malformed")
    restored = capture_run(str(value.get("runId") or ""), sources)
    if restored.doctrine_hash != value.get("doctrineHash"):
        raise DoctrineLifecycleError("doctrine snapshot authority hash was changed")
    lock = DoctrineLock(restored.run_id, restored.doctrine_hash, restored.files,
                        str(kind), hashes[0], hashes[1], tuple(proposal_ids), hashes[2])
    if lock.receipt().get("lockHash") != value.get("lockHash"):
        raise DoctrineLifecycleError("doctrine snapshot receipt was changed")
    return lock

def source_drift(lock: DoctrineLock, sources: Mapping[str, str]) -> tuple[str, ...]:
    """Report live-file drift without changing what the running edit reads."""
    found = {item.path: item.digest for item in _files(sources)}
    pinned = {item.path: item.digest for item in lock.files}
    return tuple(sorted(path for path in set(found) | set(pinned)
                        if found.get(path) != pinned.get(path)))


def draft_proposal(base: DoctrineLock, value: Mapping[str, object],
                   observations: Sequence[object]) -> LessonProposal:
    """Create a non-active proposal after validating its observation lineage."""
    ids = tuple(str(item) for item in value.get("observationIds", ()))
    observed = tuple(getattr(item, "observation_id", None) for item in observations)
    if not ids or len(ids) != len(set(ids)) or sorted(ids) != sorted(observed):
        raise DoctrineLifecycleError("proposal must cite exactly its observations")
    if any(getattr(item, "doctrine_hash", None) != base.doctrine_hash
           or getattr(item, "run_id", None) != base.run_id for item in observations):
        raise DoctrineLifecycleError("proposal observations came from another run")
    required = ("proposalId", "lessonText", "targetPath", "authorKind")
    if any(not isinstance(value.get(key), str) or not value.get(key) for key in required):
        raise DoctrineLifecycleError("proposal fields must be non-empty strings")
    if value.get("authorKind") not in ("operator", "agent-draft"):
        raise DoctrineLifecycleError("proposal author kind is not recognized")
    base.text(str(value["targetPath"]))
    return LessonProposal(str(value["proposalId"]), base.doctrine_hash, ids,
                          str(value["lessonText"]), str(value["targetPath"]),
                          str(value["authorKind"]))


def build_candidate(base: DoctrineLock, sources: Mapping[str, str],
                    proposals: Sequence[LessonProposal]) -> DoctrineCandidate:
    """Build exact candidate bytes while leaving ``base`` active and untouched."""
    if not proposals or any(item.status != "proposed" for item in proposals):
        raise DoctrineLifecycleError("candidate requires proposed lessons")
    if any(item.base_doctrine_hash != base.doctrine_hash for item in proposals):
        raise DoctrineLifecycleError("candidate proposal base is stale")
    ids = tuple(sorted(item.proposal_id for item in proposals))
    if len(ids) != len(set(ids)):
        raise DoctrineLifecycleError("candidate proposal ids are duplicated")
    files = _files(sources)
    digest = _doctrine_hash(files)
    if digest == base.doctrine_hash:
        raise DoctrineLifecycleError("candidate doctrine is unchanged")
    return DoctrineCandidate(base.doctrine_hash, digest, files, ids)


def _check_rows(rows: object, label: str) -> None:
    if not isinstance(rows, list) or not rows:
        raise DoctrineLifecycleError(f"promotion requires {label}")
    ids = []
    for row in rows:
        valid = (isinstance(row, dict) and isinstance(row.get("id"), str)
                 and row.get("status") == "pass"
                 and isinstance(row.get("artifactHash"), str)
                 and _SHA.fullmatch(row["artifactHash"]))
        if not valid:
            raise DoctrineLifecycleError(f"promotion {label} did not all pass")
        ids.append(row["id"])
    if len(ids) != len(set(ids)):
        raise DoctrineLifecycleError(f"promotion {label} are duplicated")


def _check_gate(candidate: DoctrineCandidate, gate: Mapping[str, object]) -> str:
    approval = gate.get("operatorApproval")
    verification = gate.get("verification")
    if not isinstance(approval, dict) or approval.get("actor") != "operator" \
            or approval.get("decision") != "approve" \
            or approval.get("candidateDoctrineHash") != candidate.candidate_doctrine_hash:
        raise DoctrineLifecycleError("promotion requires explicit operator approval")
    if sorted(approval.get("proposalIds", ())) != list(candidate.proposal_ids):
        raise DoctrineLifecycleError("operator did not approve the candidate proposals")
    if not isinstance(verification, dict) \
            or verification.get("candidateDoctrineHash") != candidate.candidate_doctrine_hash \
            or verification.get("regressionCount") != 0:
        raise DoctrineLifecycleError("promotion verification is stale or regressed")
    _check_rows(verification.get("tests"), "tests")
    _check_rows(verification.get("evals"), "evals")
    next_run_id = gate.get("nextRunId")
    if not isinstance(next_run_id, str) or not next_run_id:
        raise DoctrineLifecycleError("promotion has no next run id")
    return next_run_id


def promote_for_next_run(current: DoctrineLock, candidate: DoctrineCandidate,
                         proposals: Sequence[LessonProposal],
                         gate: Mapping[str, object]) -> DoctrineLock:
    """Activate tested doctrine only in a distinct, not-yet-started run."""
    if candidate.base_doctrine_hash != current.doctrine_hash:
        raise DoctrineLifecycleError("promotion candidate base is not current")
    if tuple(sorted(item.proposal_id for item in proposals)) != candidate.proposal_ids:
        raise DoctrineLifecycleError("promotion proposal set changed")
    next_run_id = _check_gate(candidate, gate)
    if next_run_id == current.run_id:
        raise DoctrineLifecycleError("doctrine cannot change inside a running edit")
    return DoctrineLock(next_run_id, candidate.candidate_doctrine_hash,
                        candidate.files, "promotion", current.doctrine_hash,
                        current.doctrine_hash, candidate.proposal_ids, _hash(gate))


def rollback_for_next_run(current: DoctrineLock, target: DoctrineLock,
                          gate: Mapping[str, object]) -> DoctrineLock:
    """Restore the exact previous lock, also only at a next-run boundary."""
    approval = gate.get("operatorApproval")
    next_run_id = gate.get("nextRunId")
    valid = (isinstance(approval, dict) and approval.get("actor") == "operator"
             and approval.get("decision") == "approve"
             and approval.get("action") == "rollback"
             and isinstance(approval.get("reason"), str) and approval.get("reason"))
    if not valid:
        raise DoctrineLifecycleError("rollback requires an operator reason")
    if target.doctrine_hash != current.rollback_doctrine_hash:
        raise DoctrineLifecycleError("rollback target is not the recorded prior doctrine")
    if not isinstance(next_run_id, str) or not next_run_id or next_run_id == current.run_id:
        raise DoctrineLifecycleError("rollback must activate in a different run")
    return DoctrineLock(next_run_id, target.doctrine_hash, target.files,
                        "rollback", current.doctrine_hash, current.doctrine_hash,
                        (), _hash(gate))
