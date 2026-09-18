"""Immutable automated-QC receipt storage below candidate staging."""
from __future__ import annotations

import os
import stat
import tempfile

from edit.cut_repair_candidate_qc_types import (
    CandidateAuthority,
    CandidateQcContractError,
    QcRun,
    QcTools,
)
from edit.cut_repair_context_sources import canonical_bytes, digest


def ensure_real_directory(path: str) -> None:
    """Create/reopen and fsync one non-symlink authority directory."""
    try:
        os.mkdir(path, mode=0o700)
    except FileExistsError:
        pass
    if os.path.islink(path) or os.path.realpath(path) != path:
        raise CandidateQcContractError(
            "candidate QC authority path is not a real directory")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) \
        | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise CandidateQcContractError(
                "candidate QC authority path is not a directory")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_all(descriptor: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(descriptor, payload[offset:])
        if written <= 0:
            raise OSError("candidate QC immutable write made no progress")
        offset += written


def _read_all(descriptor: int) -> bytes:
    chunks = []
    while True:
        chunk = os.read(descriptor, 64 * 1024)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def _read_existing(path: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise CandidateQcContractError(
            "candidate QC authority is not a private regular file") from exc
    try:
        row = os.fstat(descriptor)
        if not stat.S_ISREG(row.st_mode) or row.st_nlink != 1:
            raise CandidateQcContractError(
                "candidate QC authority is not a private regular file")
        return _read_all(descriptor)
    finally:
        os.close(descriptor)


def _stage_payload(descriptor: int, payload: bytes) -> None:
    try:
        _write_all(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _link_or_verify(temporary: str, path: str, payload: bytes) -> None:
    try:
        os.link(temporary, path, follow_symlinks=False)
    except FileExistsError:
        if _read_existing(path) != payload:
            raise CandidateQcContractError(
                f"immutable candidate QC conflict at {path}")


def _fsync_directory(path: str) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def publish_json(path: str, value: dict) -> str:
    """Durably link complete canonical bytes once, or prove exact replay."""
    payload = canonical_bytes(value)
    directory_path = os.path.dirname(path)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{os.path.basename(path)}.", dir=directory_path)
    try:
        _stage_payload(descriptor, payload)
        _link_or_verify(temporary, path, payload)
        _fsync_directory(directory_path)
    finally:
        os.unlink(temporary)
        _fsync_directory(directory_path)
    return digest(value)


def create_qc_run(
    authority: CandidateAuthority,
    tools: QcTools,
    controller_hash: str,
) -> QcRun:
    """Create/reopen one deterministic candidate/tool/controller run."""
    invocation = digest({
        "schemaVersion": 1,
        "kind": "cut-repair-automated-qc-invocation",
        "preparationHash": authority.preparation_hash,
        "candidateDescriptorHash":
            authority.package["reviewCandidateDescriptorHash"],
        "candidateSha256": authority.candidate_sha256,
        "operationHash": authority.descriptor["operationHash"],
        "alternateTakeSelectionHash":
            authority.alternate_take_selection_hash,
        "toolManifestHash": tools.manifest_hash,
        "controllerSha256": controller_hash,
    })
    descriptor_dir = os.path.dirname(
        authority.package["reviewCandidateDescriptorPath"])
    qc_root = os.path.join(descriptor_dir, "qc")
    ensure_real_directory(qc_root)
    directory = os.path.join(qc_root, invocation)
    ensure_real_directory(directory)
    return QcRun(authority, tools, invocation, directory)


class ReceiptStore:
    """Buffer lane receipts until every input/tool is reobserved."""

    def __init__(self, run: QcRun) -> None:
        self.run = run

    def passed(self, lane: str, receipt: dict, method: str) -> dict:
        """Hold one gate-compatible receipt outside published authority."""
        return {
            "status": receipt["status"],
            "method": method,
            "_lane": lane,
            "_receipt": receipt,
        }


def publish_lanes(run: QcRun, lanes: dict[str, dict]) -> dict[str, dict]:
    """Publish buffered pass receipts only after terminal reobservation."""
    result = {}
    for lane, value in lanes.items():
        if value["status"] == "blocked":
            result[lane] = value
            continue
        receipt = value.get("_receipt")
        if value.get("_lane") != lane or not isinstance(receipt, dict):
            raise CandidateQcContractError("candidate QC receipt buffer is stale")
        receipt_path = os.path.join(run.directory, f"{lane}.json")
        result[lane] = {
            "status": receipt["status"],
            "method": value["method"],
            "receiptHash": publish_json(receipt_path, receipt),
            "receiptPath": receipt_path,
        }
    return result
