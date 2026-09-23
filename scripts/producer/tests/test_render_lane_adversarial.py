"""Adversarial retained-result parsing, independent of retired R0 execution."""
from __future__ import annotations

from pathlib import Path

from _render_result_fixture import HistoricalResultFixture
from _render_lane_proof import IMAGE_ID, ProofInputs, build_full_proof
from headless.render_lane_cache import CacheOwnershipError


class RenderLaneAdversarialTests(HistoricalResultFixture):
    """Retain path, inode, key, format and copy attacks on actual readers."""

    def test_worker_result_cannot_escape_attempt_cache(self) -> None:
        value = self._value()
        outside = self.root / (self.seal.key + ".mov")
        outside.write_bytes(b"outside")
        value["path"] = str(outside)
        with self.assertRaisesRegex(RuntimeError, "escaped"):
            self._validate(value)

    def test_worker_result_symlink_inside_cache_is_rejected(self) -> None:
        value = self._value()
        path = Path(value["path"])
        target = path.with_name("b" * 64 + ".mov")
        path.rename(target)
        path.symlink_to(target.name)
        with self.assertRaisesRegex(RuntimeError, "escaped"):
            self._validate(value)

    def test_worker_cache_directory_replacement_is_rejected(self) -> None:
        value = self._value()
        cache = Path(self.binding.cache_dir)
        cache.rename(cache.parent / "graphics-cache-original")
        cache.mkdir(mode=0o700)
        replacement = Path(value["path"])
        replacement.write_bytes(b"rendered")
        replacement.chmod(0o600)
        with self.assertRaisesRegex(CacheOwnershipError, "cache directory identity changed"):
            self._validate(value)

    def test_worker_result_must_match_request_path_and_media_proof(self) -> None:
        for label in ("empty", "wrong-name", "wrong-format", "wrong-kind", "wrong-proof"):
            with self.subTest(label=label):
                value = self._value()
                self._malform(value, label)
                with self.assertRaises(RuntimeError):
                    self._validate(value)

    def _malform(self, value: dict, label: str) -> None:
        """Change one independently checked result dimension."""
        path = Path(value["path"])
        if label == "empty":
            path.write_bytes(b"")
            return
        if label == "wrong-name":
            renamed = path.with_name("wrong-name.mov")
            path.rename(renamed)
            value["path"] = str(renamed)
            return
        if label == "wrong-format":
            value["fmt"] = "mp4"
            return
        if label == "wrong-kind":
            value["kind"] = "wrong-kind"
            return
        value["proof"]["asset"]["sha256"] = "0" * 64
        self._rewrite_sidecar(value)

    def test_self_consistent_wrong_copy_proof_is_rejected(self) -> None:
        value = self._value()
        value["proof"] = build_full_proof(
            Path(value["path"]), self.seal.key, IMAGE_ID,
            ProofInputs(("WRONG",), self.seal.snapshot))
        with self.assertRaisesRegex(RuntimeError, "copy"):
            self._validate(value)
