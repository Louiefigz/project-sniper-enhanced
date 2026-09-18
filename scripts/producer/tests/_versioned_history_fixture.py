"""Real sealed mixed-version ancestry for recursive history tests."""

from __future__ import annotations

import json
from dataclasses import dataclass

from _approved_parent_loader_documents import AuthorityDocuments
from _approved_parent_loader_values import artifact_path, canonical
from _assembly_receipt_fixture import assembly_fixture
from _genesis_r1_fixture import genesis_r1_fixture
from _versioned_disk_authorities import (
    _VerificationParts,
    _commit_document,
    _quality_card_document,
    _quality_receipt_document,
    _raw_ref,
    _receipt_sections,
    _verification_document,
)
from headless.artifact_contract import ArtifactRefV1
from headless.generation_schema import parse_generation_commit
from headless.generation_verification import payload_manifest_digest
from headless.operation_wire import parent_document
from headless.repair_intent import ParentRefV1
from headless.versioned_parent_authority import ParentAuthorityV2

_R0_GENERATION = "99999999-9999-4999-8999-999999999999"
_R0_ATTEMPT = "99999999-9999-4999-8999-999999999998"
_V2_GENERATION = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_V2_ATTEMPT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaab"
_FORK_GENERATION = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


@dataclass(frozen=True)
class HistoryPayload:
    """One exact generation closure plus its semantic lineage identities."""

    commit: object
    files: dict[str, bytes]
    classes: dict[str, str]
    plan_digest: str
    receipt: ArtifactRefV1
    receipt_class: str

    def ref(self, sequence: int) -> ParentRefV1:
        return ParentRefV1(
            self.commit.authority_id,
            sequence,
            self.commit.generation_id,
            self.commit.commit_digest,
            self.plan_digest,
        )


def _artifact(ref: dict) -> ArtifactRefV1:
    return ArtifactRefV1(ref["path"], ref["sha256"], ref["sizeBytes"])


def _genesis_payload() -> HistoryPayload:
    value = genesis_r1_fixture()
    card = value.inputs.approved_card
    return HistoryPayload(
        value.inputs.commit,
        dict(value.files),
        dict(value.classes),
        card.plan.approved_plan_digest,
        card.origin.receipt,
        "initialization-origin-receipt-v1",
    )


def _identity(card: dict, generation: str, attempt: str) -> None:
    card["identity"]["generationId"] = generation
    card["identity"]["attemptId"] = attempt


def _v2_payload(
    parent: ParentRefV1,
    parent_authority: ParentAuthorityV2,
    generation: str,
    attempt: str,
) -> HistoryPayload:
    r0 = AuthorityDocuments()
    files, classes = dict(r0.files), dict(r0.classes)
    card = _quality_card_document(r0, parent)
    _identity(card, generation, attempt)
    receipt_raw = canonical(
        _quality_receipt_document(r0, card, parent, parent_authority)
    )
    receipt_path = artifact_path("assembly-receipt-v1")
    files[receipt_path] = receipt_raw
    classes[receipt_path] = "assembly-receipt-v2"
    card["output"]["assemblyReceipt"] = _raw_ref(receipt_path, receipt_raw)
    card_raw = canonical(card)
    card_path = artifact_path("approved-parent-v1")
    files[card_path] = card_raw
    classes[card_path] = "quality-pass-approved-card-v2"
    verify_path = artifact_path("generation-verification-v1")
    files[verify_path] = b"provisional"
    classes[verify_path] = "quality-pass-generation-verification-v2"
    provisional = parse_generation_commit(
        _commit_document(card, parent, files, classes)
    )
    parts = _VerificationParts(
        provisional, card, card_raw, receipt_raw, parent, parent_authority
    )
    files[verify_path] = canonical(_verification_document(parts))
    commit = parse_generation_commit(_commit_document(card, parent, files, classes))
    receipt = _artifact(card["output"]["assemblyReceipt"])
    return HistoryPayload(
        commit,
        files,
        classes,
        card["plan"]["approvedPlanDigest"],
        receipt,
        "assembly-receipt-v2",
    )


def _r0_receipt(r0: AuthorityDocuments, card: dict, parent: HistoryPayload) -> bytes:
    document = json.loads(assembly_fixture().receipt.document_json)
    document.update(
        {
            "requestDigest": card["identity"]["requestDigest"],
            "qualityPolicyId": card["policies"]["qualityPolicyId"],
            "parent": parent_document(parent.ref(2)),
            "parentAssemblyReceiptSha256": parent.receipt.sha256,
            **_receipt_sections(r0, card),
        }
    )
    proof = document["compositor"]
    proof["framesIn"] = card["base"]["media"]["facts"]["frameCount"]
    proof["framesOut"] = card["output"]["final"]["facts"]["frameCount"]
    proof["audio"]["baseSha256"] = card["base"]["media"]["artifact"]["sha256"]
    proof["audio"]["finalSha256"] = proof["audio"]["baseSha256"]
    return canonical(document)


def _r0_commit(
    card: dict,
    parent: ParentRefV1,
    files: dict[str, bytes],
    classes: dict[str, str],
) -> object:
    document = {
        "schemaVersion": 1,
        **card["identity"],
        **card["policies"],
        "expectedParent": parent_document(parent),
        "approvedParentPath": artifact_path("approved-parent-v1"),
        "files": [
            {"artifactClass": classes[path], **_raw_ref(path, raw)}
            for path, raw in sorted(files.items())
        ],
    }
    return parse_generation_commit(canonical(document))


def _r0_verification(commit: object, card: dict, card_raw: bytes) -> bytes:
    payload = tuple(
        row
        for row in commit.files
        if row.artifact_class != "generation-verification-v1"
    )
    return canonical(
        {
            "schemaVersion": 1,
            "status": "pass",
            "profile": "deterministic-mp4-r0-v1",
            **card["identity"],
            **card["policies"],
            "approvedParent": _raw_ref(artifact_path("approved-parent-v1"), card_raw),
            "payloadManifestDigest": payload_manifest_digest(payload),
        }
    )


def _r0_payload(parent: HistoryPayload) -> HistoryPayload:
    r0 = AuthorityDocuments()
    files, classes = dict(r0.files), dict(r0.classes)
    card = json.loads(files[r0.commit.approved_parent_path])
    _identity(card, _R0_GENERATION, _R0_ATTEMPT)
    receipt_raw = _r0_receipt(r0, card, parent)
    receipt_path = artifact_path("assembly-receipt-v1")
    files[receipt_path] = receipt_raw
    card["output"]["assemblyReceipt"] = _raw_ref(receipt_path, receipt_raw)
    card_raw = canonical(card)
    card_path = artifact_path("approved-parent-v1")
    files[card_path] = card_raw
    verify_path = artifact_path("generation-verification-v1")
    files[verify_path] = b"provisional"
    parent_ref = parent.ref(2)
    provisional = _r0_commit(card, parent_ref, files, classes)
    files[verify_path] = _r0_verification(provisional, card, card_raw)
    commit = _r0_commit(card, parent_ref, files, classes)
    receipt = _artifact(card["output"]["assemblyReceipt"])
    return HistoryPayload(
        commit,
        files,
        classes,
        card["plan"]["approvedPlanDigest"],
        receipt,
        "assembly-receipt-v1",
    )


def mixed_payloads(
    wrong_parent_receipt: bool = False,
    cycle: bool = False,
    wrong_genesis_receipt_kind: bool = False,
) -> tuple[HistoryPayload, ...]:
    """Build genesis R1, V2, frozen R0, then V2 in selected order."""
    genesis = _genesis_payload()
    origin = ParentAuthorityV2("genesis-origin", genesis.receipt_class, genesis.receipt)
    if wrong_genesis_receipt_kind:
        origin = ParentAuthorityV2(
            "prior-assembly", "assembly-receipt-v2", genesis.receipt
        )
    first = _v2_payload(
        genesis.ref(1),
        origin,
        "77777777-7777-4777-8777-777777777777",
        "88888888-8888-4888-8888-888888888888",
    )
    r0 = _r0_payload(first)
    parent_receipt = r0.receipt
    if wrong_parent_receipt:
        parent_receipt = ArtifactRefV1(
            parent_receipt.relative_path, "f" * 64, parent_receipt.size_bytes
        )
    prior = ParentAuthorityV2("prior-assembly", r0.receipt_class, parent_receipt)
    parent_ref = r0.ref(3)
    if cycle:
        parent_ref = ParentRefV1(
            r0.commit.authority_id,
            3,
            _V2_GENERATION,
            "e" * 64,
            r0.plan_digest,
        )
    final = _v2_payload(parent_ref, prior, _V2_GENERATION, _V2_ATTEMPT)
    return genesis, first, r0, final
