"""TEST V8 metadata and real tiny same-pass file identities; no isolated admission."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from fractions import Fraction

from _guided_presenter_observation_fixture import ObservationFixture
from _guided_proposal_presenter_fixture import values
from cut_preview_io import digest
from graphics.presenter_layout_contract import declaration_payload
from guided_opening_inputs import OpeningInputs
from guided_presenter_capture import PresenterCaptureContext
from guided_presenter_profile import PRESENTER_PROFILE
from guided_proposal_presenter import guided_presenter_policy
from headless.external_media_snapshot import ExternalMediaSnapshot, observe_external_media_snapshot
from headless.external_media_verification import SourceVerificationRuntime
from ingest_media_observation import SourceVerificationCapture


def bind_capture_documents(documents: dict) -> None:
    """Bind TEST V2 metadata hashes; not a server review or execution authority."""
    packet, candidate = documents["readinessPacket"], documents["candidatePlan"]
    evidence = packet["evidence"]
    documents["occurrences"] = {key: deepcopy(evidence[key]) for key in ("anchors", "occurrences", "segments")}
    authority = documents["authority"]
    authority.update(candidatePlanHash=digest(candidate), occurrenceEvidenceHash=digest(documents["occurrences"]),
        core={"startFrame": 0, "endFrameExclusive": 24}, review={"startFrame": 0, "endFrameExclusive": 24},
        profile=PRESENTER_PROFILE)
    graphics = documents.get("frameBindings", {}).get("graphics", [])
    bindings = {"schemaVersion": 2, "kind": "guided-frame-presentation-bindings",
        "scope": "controller-frames-and-declared-presentation-not-rendered-proof",
        "frameRate": authority["frameRate"], "totalFrames": authority["totalFrames"],
        "targetHash": digest(authority["target"]), "candidatePlanHash": authority["candidatePlanHash"],
        "occurrenceEvidenceHash": authority["occurrenceEvidenceHash"], "graphics": graphics,
        "unboundInheritedGraphicIds": [], "presenterLayouts": deepcopy(candidate["presenterLayouts"])}
    documents["frameBindings"] = bindings
    packet["executionBindings"] = deepcopy(bindings)
    packet["candidate"] = deepcopy(candidate)
    authority["frameBindingsHash"] = digest(bindings)


def add_capture_graphic(documents: dict, span: tuple[int, int]) -> None:
    """Append a real-shaped TEST operation/entry/binding, not an observed native graphic."""
    packet, candidate = documents["readinessPacket"], documents["candidatePlan"]
    operations, track = packet["proposal"]["operations"], candidate["graphicsTrack"]
    order, index = len(track), len(operations)
    presentation = {"schemaVersion": 1, "anchor": "own-screen", "placement": "full-canvas",
        "compositeMode": "normal", "baseTreatment": "preserve", "rationale": "TEST whole-card placement"}
    rate = Fraction(documents["authority"]["frameRate"])
    entry = {"id": f"TEST-graphic-{order}", "kind": "statement-card", "anchor": "own-screen",
        "outStart": float(Fraction(span[0], 1) / rate), "outEnd": float(Fraction(span[1], 1) / rate),
        "spec": {"text": "TEST declared text"}}
    operation = {key: None for key in operations[0]}
    operation.update(type="catalog-graphic", clauseIndex=0, beatIndex=0, catalogKind="statement-card",
        variables=[{"name": "text", "value": "TEST declared text"}], startAnchor=span[0],
        endAnchorExclusive=span[1], presentation=deepcopy(presentation), reason="TEST bounded frame declaration.")
    operations.append(operation)
    packet["proposal"]["clauses"][0]["operationIndices"].append(index)
    track.append(entry)
    documents["frameBindings"]["graphics"].append({"graphicId": entry["id"], "operationIndex": index,
        "order": order, "startFrame": span[0], "endFrameExclusive": span[1],
        "presentation": presentation, "entryHash": digest(entry)})
    bind_capture_documents(documents)


class PresenterCaptureFixture:
    """Actual policy/parser and pin operations around explicitly stubbed probe results."""

    def __init__(self, repeated: bool = False) -> None:
        """Use one TEST original clock and honest sentinel video/receipt metadata."""
        self.probe = ObservationFixture()
        self.inputs = self._inputs(repeated)
        tool = self.probe.runtime.ffprobe
        self.context = PresenterCaptureContext({"ffprobe": {"path": tool.path, "sha256": tool.sha256}},
            str(self.probe.root), self.probe.deadline, lambda: None)

    def _manifest(self) -> tuple[dict, dict]:
        """Build TEST entry declarations, not production receipt validation evidence."""
        value = self.probe.selected.admission
        row = {"id": value.asset_id, "kind": "video", "originalPath": value.original_path,
            "path": value.snapshot_path, "sourceSha256": value.source_sha256,
            "sourceSizeBytes": value.source_size_bytes, "admissionReceiptPath": value.receipt_path,
            "admissionReceiptSha256": value.receipt_sha256, "duration": 24 * 1001 / 30000, "resolution": [64, 36]}
        entry = {"lane": value.lane, "mediaKind": value.media_kind, "originalPath": value.original_path,
            "snapshotPath": value.snapshot_path, "sha256": value.source_sha256, "sizeBytes": value.source_size_bytes,
            "admissionReceiptPath": value.receipt_path, "admissionReceiptSha256": value.receipt_sha256}
        return {"sources": [{"id": "TEST-source"}], "broll": [row]}, entry

    def _documents(self, repeated: bool) -> tuple[dict, dict]:
        """Derive actual closed V8 requests over 48 synthetic output frames."""
        accepted, _, packet, _ = values()
        manifest, entry = self._manifest()
        # Native destination is declared only; the stubbed asset remains64x36.
        accepted["target"].update(width=1920, height=1080, fps=30000 / 1001)
        accepted.pop("unrelated")
        accepted.update(captions={"burn": False}, graphicsTrack=[])
        accepted["cutTrack"] = [{"sourceId": "TEST-source", "start": 0, "end": 48 * 1001 / 30000}]
        evidence = packet["evidence"]
        evidence.update(target=deepcopy(accepted["target"]), frameRate="30000/1001", totalFrames=48,
            anchors=list(range(49)), occurrences=[],
            segments=[{"index": 0, "sourceId": "TEST-source", "startFrame": 0, "endFrameExclusive": 48}],
            presenterPolicy=guided_presenter_policy(accepted, manifest))
        proposal = packet["proposal"]
        proposal.update(openingEndAnchor=48, continuityEndAnchor=48)
        proposal["beats"][0]["endAnchorExclusive"] = 48
        operation = proposal["operations"][0]
        operation.update(startAnchor=2, endAnchorExclusive=18, presenterLayout=declaration_payload(self.probe.selected.geometry))
        if repeated:
            proposal["operations"].append({**deepcopy(operation), "startAnchor": 26, "endAnchorExclusive": 42})
            proposal["clauses"][0]["operationIndices"].append(1)
        candidate = deepcopy(accepted)
        candidate["presenterLayouts"] = [{"operationIndex": index, "startFrame": row["startAnchor"],
            "endFrameExclusive": row["endAnchorExclusive"], "layout": deepcopy(row["presenterLayout"])}
            for index, row in enumerate(proposal["operations"])]
        authority = {key: deepcopy(evidence[key]) for key in ("target", "frameRate", "totalFrames")}
        return {"acceptedPlan": accepted, "candidatePlan": candidate, "readinessPacket": packet,
                "manifest": manifest, "authority": authority}, entry

    def _inputs(self, repeated: bool) -> OpeningInputs:
        """Retain a genuine descriptor-linked tiny hash pass, with TEST admission metadata."""
        documents, entry = self._documents(repeated)
        bind_capture_documents(documents)
        source = self.probe.source
        runtime = SourceVerificationRuntime(self.probe.deadline.remaining)
        capture = SourceVerificationCapture(runtime)
        capture.add(observe_external_media_snapshot(ExternalMediaSnapshot(
            source.path, source.sha256, source.size_bytes, 0, 0), runtime))
        captured = capture.finish([entry])
        return OpeningInputs(self.probe.root / "TEST-input.json", "a" * 64,
                             {"TEST": "not a 14-document admission", "profile": PRESENTER_PROFILE}, documents, captured)

    def noop(self) -> OpeningInputs:
        """A real V8 no-layout declaration, not a bypassed request validator."""
        from _guided_proposal_presenter_fixture import noop
        accepted, candidate, packet, manifest = values(operations=[noop()])
        return replace(self.inputs, verified_media=None, documents={"acceptedPlan": accepted,
            "candidatePlan": candidate, "readinessPacket": packet, "manifest": manifest})

    def close(self) -> None:
        """Dispose of only this small TEST-owned fixture."""
        self.probe.close()
