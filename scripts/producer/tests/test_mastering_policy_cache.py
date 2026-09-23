"""Processing-policy provenance cannot be upgraded by rehashing an old plan."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import assemble
import fingerprints
from audio import master
from audio import base_audio


class MasteringPolicyCacheTests(unittest.TestCase):
    """An old/missing-policy base must not become a current or audio-only hit."""

    def setUp(self) -> None:
        """Create non-media dispatch fixtures; no decode quality is asserted."""
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.plan = {"cutTrack": [{"sourceId": "a", "start": 0, "end": 2}]}
        self.base = self.root / "base_final.mp4"
        self.base.write_bytes(b"dispatch-only fixture")
        self.record_path = self.root / "base.fingerprint.json"
        (self.root / "base_plan.json").write_text(json.dumps(self.plan))

    def _record(self, version: object) -> None:
        """Write an old/new observed policy independently of the current builder."""
        from test_base_reuse import bound_record
        record = bound_record(self.base, self.plan)
        record.pop("masteringPolicyVersion", None)
        if version is not None:
            record["masteringPolicyVersion"] = version
        self.record_path.write_text(json.dumps(record))

    def test_new_record_identifies_actual_latency_compensated_policy(self) -> None:
        self.assertEqual(fingerprints.fingerprint_record(self.plan).get(
            "masteringPolicyVersion"), 3)

    def test_snapshot_refresh_never_upgrades_or_invents_observed_audio_policy(self) -> None:
        for version in (None, 1, 2, True, "3"):
            with self.subTest(version=version):
                self._record(version)
                observed = fingerprints.recorded_fingerprints(str(self.record_path))
                self.assertEqual(observed.get("masteringPolicyVersion"), version)
                self.assertEqual(assemble._base_state(
                    str(self.base), self.plan, str(self.record_path)), "stale")

    def test_old_policy_cannot_enter_audio_only_rebuild(self) -> None:
        self._record(2)
        edited = {**self.plan, "audioGain": [{"outStart": 0, "outEnd": 1, "dB": -2}]}
        self.assertEqual(assemble._base_state(
            str(self.base), edited, str(self.record_path)), "stale")

    def test_current_policy_keeps_normal_plan_dispatch(self) -> None:
        self._record(master.MASTERING_POLICY_VERSION)
        self.assertEqual(assemble._base_state(
            str(self.base), self.plan, str(self.record_path)), "current")

    def test_old_crash_intent_recovery_cannot_claim_new_mastering_policy(self) -> None:
        self._record(2)
        intent = {"newBaseHash": fingerprints.file_sha256(str(self.base)),
                  "oldBaseHash": "a" * 64, "plan": self.plan}
        Path(base_audio.audio_intent_path(str(self.record_path))).write_text(json.dumps(intent))
        self.assertEqual(base_audio.recover_audio_intent(
            str(self.base), str(self.record_path)), "finalized")
        observed = fingerprints.recorded_fingerprints(str(self.record_path))
        self.assertIsNone(observed.get("masteringPolicyVersion"))
        self.assertEqual(assemble._base_state(
            str(self.base), self.plan, str(self.record_path)), "stale")


if __name__ == "__main__":
    unittest.main(verbosity=2)
