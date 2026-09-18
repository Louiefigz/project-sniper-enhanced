"""Acyclic canonical R0 documents for approved-parent loader tests."""

from __future__ import annotations

import hashlib

from _common import pl  # noqa: F401
from _approved_parent_loader_quality import set_quality_payloads
from _approved_parent_loader_values import (
    ATTEMPT,
    AUTHORITY,
    COMMIT_DOMAIN,
    EXECUTION,
    FALLBACK,
    GENERATION,
    PAYLOAD_DOMAIN,
    PROVENANCE,
    QUALITY,
    REPAIR,
    REQUEST,
    UNIT,
    artifact_path,
    canonical,
    clips,
    plan,
    policy_payloads,
)
from fingerprints import base_plan_digest, plan_content_hash
from headless.artifact_contract import ArtifactRefV1
from headless.generation_profile import R0_GENERATION_ARTIFACT_CLASS_COUNTS
from headless.generation_schema import parse_generation_commit
from headless.generation_verification import payload_manifest_digest
from headless.quality_pass_contract import graphic_render_intent_digest
from headless.repair_intent import ParentRefV1, approved_plan_digest


class AuthorityDocuments:
    """Build all 42 rows without introducing a verification digest cycle."""

    def __init__(self, scenario: str = "success") -> None:
        self.scenario = scenario
        self.plan = plan()
        self.files, self.classes = self._payload_files()
        self._set_semantic_payloads()
        self._set_descriptor()
        provisional = parse_generation_commit(self.commit_document())
        self._set_verification(provisional)
        self.commit_raw = canonical(self.commit_document())
        self.commit = parse_generation_commit(self.commit_raw)
        self.publication_seq = 2 if scenario == "genesis-sequence" else 1
        self.current_raw = canonical(self.current_document())

    def _payload_files(self) -> tuple[dict[str, bytes], dict[str, str]]:
        files, classes = {}, {}
        for artifact_class, count in R0_GENERATION_ARTIFACT_CLASS_COUNTS.items():
            for ordinal in range(count):
                path = artifact_path(artifact_class, ordinal)
                files[path] = f"{artifact_class}:{ordinal}\n".encode("ascii")
                classes[path] = artifact_class
        return files, classes

    def _set_semantic_payloads(self) -> None:
        for artifact_class, raw in policy_payloads().items():
            self.files[artifact_path(artifact_class)] = raw
        if self.scenario == "policy-document":
            self.files[artifact_path("quality-policy-v1")] = canonical({"bad": True})
        self.files[artifact_path("plan-v1")] = canonical(self.plan)
        media = self.ref("graphic-media-v1")
        receipt = self.ref("graphic-render-receipt-v1")
        self.files[artifact_path("prebound-clips-v1")] = canonical(
            clips(self.plan, media, receipt)
        )
        set_quality_payloads(self)

    def ref(self, artifact_class: str, ordinal: int = 0) -> dict:
        """Return the exact current bytes as a descriptor-shaped reference."""
        path = artifact_path(artifact_class, ordinal)
        raw = self.files[path]
        return {
            "path": path,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "sizeBytes": len(raw),
        }

    def artifact_ref(self, artifact_class: str, ordinal: int = 0) -> ArtifactRefV1:
        """Return one exact typed ref from the completed commit."""
        path = artifact_path(artifact_class, ordinal)
        row = next(row for row in self.commit.files if row.path == path)
        return ArtifactRefV1(row.path, row.sha256, row.size_bytes)

    def _media(self, artifact_class: str, graphic: bool = False) -> dict:
        ref = self.ref(artifact_class)
        facts = {
            "width": 240 if graphic else 1080,
            "height": 120 if graphic else 1920,
            "durationSeconds": 2.5 if graphic else 4.0,
            "fpsNumerator": 30,
            "fpsDenominator": 1,
            "frameCount": 75 if graphic else 120,
            "sizeBytes": ref["sizeBytes"],
            "videoCodec": "prores" if graphic else "h264",
            "pixelFormat": "yuva444p12le" if graphic else "yuv420p",
            "profile": "4444" if graphic else "High",
            "alphaMode": "straight" if graphic else "none",
            "audioCodec": None if graphic else "aac",
        }
        return {"artifact": ref, "facts": facts}

    def _descriptor(self) -> dict:
        plan_raw = self.files[artifact_path("plan-v1")]
        row = self.plan["graphicsTrack"][0]
        graphic = self._media("graphic-media-v1", True)
        receipt = self.ref("graphic-render-receipt-v1")
        document = {
            "schemaVersion": 1,
            "status": "approved-private-generation",
            "realizationKind": "deterministic-mp4",
            "identity": self._identity(),
            "policies": self._policies(),
            "provenance": {
                name: self.ref(artifact_class)
                for name, artifact_class in PROVENANCE.items()
            },
            "plan": {
                "artifact": self.ref("plan-v1"),
                "approvedPlanDigest": approved_plan_digest(self.plan),
                "contentHash": plan_content_hash(self.plan),
                "baseProjectionDigest": base_plan_digest(self.plan),
            },
            "base": self._base_section(),
            "graphics": {
                "preboundClips": self.ref("prebound-clips-v1"),
                "assets": [self._graphic(row, graphic, receipt)],
            },
            "output": self._output_section(),
            "quality": self._quality_section(),
        }
        if (
            hashlib.sha256(plan_raw).hexdigest()
            != document["plan"]["artifact"]["sha256"]
        ):
            raise AssertionError("fixture plan ref is stale")
        return self._mutate_descriptor(document)

    def _identity(self) -> dict:
        return {
            "authorityId": AUTHORITY,
            "generationId": GENERATION,
            "attemptId": ATTEMPT,
            "unitId": UNIT,
            "requestDigest": REQUEST,
        }

    def _policies(self) -> dict:
        return {
            "executionPolicyId": EXECUTION,
            "repairPolicyId": REPAIR,
            "qualityPolicyId": QUALITY,
            "fallbackPolicyId": FALLBACK,
        }

    def _base_section(self) -> dict:
        return {
            "media": self._media("base-media-v1"),
            "planArtifact": self.ref("base-plan-v1"),
            "receipt": self.ref("base-receipt-v1"),
            "timelineMap": self.ref("timeline-map-v1"),
        }

    def _graphic(self, row: dict, media: dict, receipt: dict) -> dict:
        return {
            "graphicId": row["id"],
            "renderIntentDigest": graphic_render_intent_digest(row),
            "media": media,
            "receipt": receipt,
            "renderArtifactDigest": media["artifact"]["sha256"],
            "renderBuildDigest": self.ref("render-build-receipt-v1")["sha256"],
        }

    def _output_section(self) -> dict:
        return {
            "final": self._media("final-media-v1"),
            "assemblyReceipt": self.ref("assembly-receipt-v1"),
            "cover": self.ref("cover-image-v1"),
            "coverProof": self.ref("cover-proof-v1"),
            "proxyDisposition": "omitted-by-policy",
        }

    def _quality_section(self) -> dict:
        return {
            "audit": self.ref("audit-b-receipt-v1"),
            "fullDecode": self.ref("full-decode-proof-v1"),
            "effectProof": self.ref("effect-proof-v1"),
            "qcReceipt": self.ref("qc-receipt-v1"),
            "critics": [
                {"lens": "composition", "artifact": self.ref("critic-receipt-v1", 0)},
                {"lens": "editorial", "artifact": self.ref("critic-receipt-v1", 1)},
            ],
            "finalApproval": self.ref("final-approval-v3"),
        }

    def _mutate_descriptor(self, document: dict) -> dict:
        if self.scenario == "descriptor-identity":
            document["identity"]["requestDigest"] = "9" * 64
        if self.scenario == "descriptor-policy":
            document["policies"]["qualityPolicyId"] = "9" * 64
        if self.scenario == "descriptor-ref-class":
            document["plan"]["artifact"] = self.ref("render-build-receipt-v1")
        if self.scenario == "descriptor-ref-digest":
            document["plan"]["artifact"]["sha256"] = "0" * 64
        return document

    def _set_descriptor(self) -> None:
        self.files[artifact_path("approved-parent-v1")] = canonical(self._descriptor())

    def _verification(self, provisional) -> dict:
        payload = tuple(
            row
            for row in provisional.files
            if row.artifact_class != "generation-verification-v1"
        )
        return {
            "schemaVersion": 1,
            "status": "pass",
            "profile": "deterministic-mp4-r0-v1",
            **self._identity(),
            **self._policies(),
            "approvedParent": self.ref("approved-parent-v1"),
            "payloadManifestDigest": payload_manifest_digest(payload),
        }

    def _set_verification(self, provisional) -> None:
        document = self._verification(provisional)
        if self.scenario == "verification-mismatch":
            document["requestDigest"] = "9" * 64
        if self.scenario == "verification-self-reference":
            document["approvedParent"] = self.ref("generation-verification-v1")
        if self.scenario == "verification-self-inclusion":
            document["payloadManifestDigest"] = self._full_payload_digest(provisional)
        self.files[artifact_path("generation-verification-v1")] = canonical(document)

    def _full_payload_digest(self, commit) -> str:
        rows = [
            {
                "artifactClass": row.artifact_class,
                "path": row.path,
                "sha256": row.sha256,
                "sizeBytes": row.size_bytes,
            }
            for row in sorted(commit.files, key=lambda item: item.path)
        ]
        return hashlib.sha256(PAYLOAD_DOMAIN + canonical(rows)).hexdigest()

    def commit_document(self) -> dict:
        rows = []
        for path in sorted(self.files):
            raw = self.files[path]
            rows.append(
                {
                    "artifactClass": self.classes[path],
                    "path": path,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "sizeBytes": len(raw),
                }
            )
        return {
            "schemaVersion": 1,
            **self._identity(),
            **self._policies(),
            "expectedParent": None,
            "approvedParentPath": artifact_path("approved-parent-v1"),
            "files": rows,
        }

    def current_document(self) -> dict:
        digest = hashlib.sha256(COMMIT_DOMAIN + self.commit_raw).hexdigest()
        return {
            "schemaVersion": 1,
            "authorityId": AUTHORITY,
            "publicationSeq": self.publication_seq,
            "generationId": GENERATION,
            "commitDigest": digest,
        }

    def expected_parent(self) -> ParentRefV1:
        """Return the exact caller expectation for this publication."""
        return ParentRefV1(
            AUTHORITY,
            self.publication_seq,
            GENERATION,
            self.commit.commit_digest,
            approved_plan_digest(self.plan),
        )
