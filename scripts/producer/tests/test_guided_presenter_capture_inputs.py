"""Actual V8/selection refusals before any tool, decode or late source hashing."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import unittest
from unittest.mock import patch

from _guided_presenter_capture_fixture import PresenterCaptureFixture
import guided_presenter_capture as capture
from guided_proposal_presenter import guided_presenter_policy
from headless.external_media_snapshot import ExternalMediaSnapshot, observe_external_media_snapshot
from headless.external_media_verification import SourceVerificationRuntime
from ingest_admission_io import canonical_bytes


class GuidedPresenterCaptureInputTests(unittest.TestCase):
    """Fixture receipts are TEST metadata, while request parsing and joins are real."""

    def setUp(self) -> None:
        """Create one repeated-asset fixture without native subprocesses."""
        self.fixture = PresenterCaptureFixture(repeated=True)
        self.addCleanup(self.fixture.close)
        self.inputs, self.context = self.fixture.inputs, self.fixture.context

    def reject(self, inputs: object, message: str) -> None:
        """Every refused acquisition must stop before opening a tool or observing media."""
        with patch.object(capture, "pin_executable") as pin, patch.object(capture, "observe_presenter_asset") as observe, \
                self.assertRaisesRegex((RuntimeError, ValueError), message), \
                capture.acquire_presenter_execution(inputs, self.context):
            self.fail("Unsupported input cannot yield an owner")
        pin.assert_not_called()
        observe.assert_not_called()

    def test_omitted_capture_missing_snapshot_and_wrong_original_sha_size_reject(self) -> None:
        """Never attach a current stat identity to a formerly claimed source hash."""
        original = self.inputs.verified_media
        variants = [None, replace(original, snapshots=()),
            replace(original, snapshots=(replace(original.snapshots[0], sha256="b" * 64),)),
            replace(original, snapshots=(replace(original.snapshots[0], size_bytes=1),))]
        for variant in variants:
            with self.subTest(variant=variant):
                self.reject(replace(self.inputs, verified_media=variant), "initial source")

    def test_changed_source_bytes_reject_before_pinning_tool(self) -> None:
        """The original successful tiny hash cannot cover a later rewritten source."""
        self.fixture.probe.path.write_bytes(b"changed TEST bytes before acquisition")
        self.reject(self.inputs, "snapshot identity changed")

    def test_unselected_base_source_identity_is_also_rechecked_without_hashing(self) -> None:
        """All original capture rows remain guarded, not only the selected presentation."""
        raw = b"TEST base source, not actual admitted media"
        sha = hashlib.sha256(raw).hexdigest()
        path = self.fixture.probe.path.parent / f"{sha}.media"
        path.write_bytes(raw)
        identity = observe_external_media_snapshot(ExternalMediaSnapshot(str(path), sha, len(raw), 0, 0),
            SourceVerificationRuntime(self.fixture.probe.deadline.remaining))
        original = self.inputs.verified_media
        entries = original.entries()
        entries.append({**entries[0], "lane": "source", "originalPath": "/TEST/base.mp4",
                        "snapshotPath": str(path), "sha256": sha, "sizeBytes": len(raw)})
        captured = replace(original, entries_json=canonical_bytes(entries), snapshots=(*original.snapshots, identity))
        path.write_bytes(b"changed TEST base source")
        with patch("headless.external_media_snapshot._hash_descriptor") as source_hash:
            self.reject(replace(self.inputs, verified_media=captured), "snapshot identity changed")
        source_hash.assert_not_called()

    def test_noop_cannot_hide_requested_windows_or_forged_policy(self) -> None:
        """Absence is a no-op only after actual V8 intent has been validated."""
        documents = deepcopy(self.inputs.documents)
        documents["candidatePlan"].pop("presenterLayouts")
        self.reject(replace(self.inputs, documents=documents), "requested windows")
        documents = deepcopy(self.fixture.noop().documents)
        documents["readinessPacket"]["evidence"]["presenterPolicy"]["acceptedBrollEnabled"] = False
        self.reject(replace(self.inputs, documents=documents), "policy differs")

    def test_explicit_empty_or_historical_layout_field_is_not_new_acquisition(self) -> None:
        """No legacy inherited layout or empty array is relabeled into this live route."""
        documents = deepcopy(self.fixture.noop().documents)
        documents["acceptedPlan"]["presenterLayouts"] = []
        documents["candidatePlan"]["presenterLayouts"] = []
        self.reject(replace(self.inputs, documents=documents), "nonempty V8")
        documents["readinessPacket"]["proposal"]["schemaVersion"] = 7
        self.reject(replace(self.inputs, documents=documents), "nonempty V8")

    def test_authority_clock_canvas_and_verified_entry_size_are_exact(self) -> None:
        """Neither a new canvas nor a projected receipt can replace the original binding."""
        for key, value in (("totalFrames", 50), ("frameRate", "30/1"), ("target", {})):
            documents = deepcopy(self.inputs.documents)
            documents["authority"][key] = value
            with self.subTest(key=key):
                self.reject(replace(self.inputs, documents=documents), "authority canvas/clock")
        entries = self.inputs.verified_media.entries()
        entries[0]["sizeBytes"] += 1
        captured = replace(self.inputs.verified_media, entries_json=canonical_bytes(entries))
        self.reject(replace(self.inputs, verified_media=captured), "verified lane/kind/path/bytes/receipt")

    def test_same_snapshot_under_two_selected_asset_ids_rejects_before_decode(self) -> None:
        """A chronologically valid pair cannot introduce ambiguous path/asset ownership."""
        documents = deepcopy(self.inputs.documents)
        second = {**documents["manifest"]["broll"][0], "id": "TEST-alias"}
        documents["manifest"]["broll"].append(second)
        documents["readinessPacket"]["evidence"]["presenterPolicy"] = guided_presenter_policy(
            documents["acceptedPlan"], documents["manifest"])
        documents["candidatePlan"]["presenterLayouts"][1]["layout"]["assetId"] = "TEST-alias"
        documents["readinessPacket"]["proposal"]["operations"][1]["presenterLayout"]["assetId"] = "TEST-alias"
        self.reject(replace(self.inputs, documents=documents), "ambiguous across asset IDs")

    def test_original_expiry_or_context_guard_failure_stops_before_acquisition(self) -> None:
        """No fresh timer, tool or source observation is created on an expired entry."""
        self.fixture.probe.deadline.expired = True
        self.reject(self.inputs, "original deadline expired")
        self.fixture.probe.deadline.expired = False

        def failed() -> None:
            """Represent a failed original phase/plan/source owner check."""
            raise RuntimeError("TEST original owner changed")

        self.context = replace(self.context, guard=failed)
        self.reject(self.inputs, "original owner changed")


if __name__ == "__main__":
    unittest.main()
