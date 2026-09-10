"""TEST receipt relationships using stub decoder facts, never a media qualification."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from _guided_presenter_read_fixture import PresenterReadFixture
from guided_presenter_body_read import PresenterBodyReadContext
from guided_presenter_read import read_presenter_graphs
from opening_prefix_contract import CompositorPrefixRequest, PrefixClock, PrefixRanges, canonical_hash
from opening_prefix_graphs import PresenterGraphProjection, presenter_projection_record
from test_opening_prefix_contract import held


def comparison_records(request: CompositorPrefixRequest) -> dict:
    """Invented TEST worker attestations; no encoded or pre-encode pixels were compared."""
    common = {"sharedCompositorCommandHash": "1" * 64, "observedCommandHash": "2" * 64,
              "pixelFormat": "yuv420p", "frameHashesSha256": "3" * 64}
    comparison = {"fullGraphPrefix": {**common, "frameCount": request.ranges.review[1]}}
    for role in ("core", "review"):
        start, end = getattr(request.ranges, role)
        comparison[role] = {**common, "frameCount": end - start, "startFrame": start,
                            "endFrameExclusive": end, "exactPreencodePixels": True}
    return comparison


def oracle_test_metadata() -> dict:
    """Explicit unobserved worker metadata, never decoded facts or runtime qualification."""
    return {"scope": "executed-preencode-graph-prefix-not-encoded-output-or-approval",
        "implementation": [], "baseSelectedVideo": {"TEST": "probe evidence is outside this fixture"},
        "graphicWorkload": {"TEST": "native workload is outside this fixture"},
        "timingMs": {"inputHash": 0.0, "baseProbe": 0.0, "graphicMetadataProbe": 0.0,
                     "preencodeOracle": 0.0, "inputRecheck": 0.0, "total": 0.0},
        "audioAuthority": "requires-separate-held-full-program-master-excerpt",
        "cleanupScope": "observed-owned-local-process-groups; no Docker invoked"}


class PresenterBodyReadFixture:
    """Keep genuine tiny file identities and explicit TEST-only output attestations."""

    def __init__(self) -> None:
        """No native process runs; inherited selected-picture decoder leaves are stubs."""
        self.original = PresenterReadFixture()
        item = self.original
        authority = item.inputs.documents["authority"]
        clock = PrefixClock(authority["frameRate"], authority["totalFrames"], 1920, 1080)
        ranges = PrefixRanges(*tuple((authority[key]["startFrame"], authority[key]["endFrameExclusive"])
                                      for key in ("core", "review")))
        self.request = CompositorPrefixRequest(item.base, (), (), (), clock, ranges)
        tool_path = item.probe.root / "TEST-ffmpeg-not-executed"
        tool_path.write_bytes(b"TEST distinct independently held ffmpeg identity; not executable")
        self.context = PresenterBodyReadContext(item.context, item.pictures, (held(tool_path), held(Path(item.tool.path))))
        evidence = read_presenter_graphs(item.records, item.context)
        self.composition = self._composition(evidence)

    def _comparison(self) -> dict:
        """Invented hashes are original-worker attestations, not newly compared pixels."""
        return comparison_records(self.request)

    def _composition(self, evidence: object) -> dict:
        """Build explicit synthetic proof around actual pure graph projections."""
        from opening_prefix_contract import HeldPrefixInput

        graphs = {}
        for role in ("full", "opening"):
            lane = PresenterGraphProjection((), None, getattr(evidence, role),
                tuple(HeldPrefixInput(**row) for row in evidence.assets))
            graphs[role] = presenter_projection_record(self.request.clock, self.request.base, lane)
        inputs = [asdict(self.request.base), *list(evidence.assets), *[asdict(row) for row in self.context.tools]]
        proof = {**oracle_test_metadata(), "schemaVersion": 2, "kind": "presenter-compositor-prefix-oracle", "status": "verified",
            "clock": asdict(self.request.clock), "fullGraphHash": canonical_hash(graphs["full"]),
            "openingGraphHash": canonical_hash(graphs["opening"]), "inputs": inputs,
            "presenterObservations": self.original.records, "comparison": self._comparison(),
            "layerPolicy": {"kind": "held-presenter-then-graphics-then-caption-pages-v1",
                "fullPresenterWindows": 2, "openingPresenterWindows": 1, "fullCaptionTail": 0, "openingCaptionTail": 0},
            "encodedOutputObserved": False, "audioCompared": False, "approvalObserved": False}
        return {"schemaVersion": 2, "kind": "verified-presenter-prefix-private-picture-composition",
            "scope": "executed-graph-bound-picture-not-decoded-output-or-approval", "outputPath": "/TEST/body/final.mp4",
            "output": {"path": "/TEST/body/final.mp4", "sha256": "4" * 64, "size_bytes": 64},
            "outputDecoded": False, "audioCompared": False, "deliveryApproved": False, "prefixOracle": proof}

    def close(self) -> None:
        """Remove only the inherited tiny TEST temporary directory."""
        self.original.close()
