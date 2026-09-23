"""Inert historical R0 result metadata, never admission or render evidence.

Tests call only the retained-result reader. No executable template is restored,
no source policy is patched, and these synthetic seals must never reach launch.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from _render_lane_proof import IMAGE_ID, ProofInputs, _archive, build_full_proof
from headless.container_io import SealedInput
from headless.overlay_source_seal import ResolvedOverlaySeal
from headless.render_lane import _validated_result
from headless.render_lane_cache import prepare_attempt_cache
from headless.resource_ledger import ResourceRequest

CONTAINER_NAME = "sniper-render-" + "d" * 32


class HistoricalResultFixture(unittest.TestCase):
    """Build synthetic metadata directly for strict result-reader regressions."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="test-r0-result-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.attempt = self.root / "attempt"
        self.attempt.mkdir(mode=0o700)
        self.identity = ("attempt", "a" * 64, "b" * 64, IMAGE_ID)
        self.binding = prepare_attempt_cache(str(self.attempt), self.identity)
        seed = self.root / "TEST-metadata"
        digest, manifest, _ = _archive(seed)
        archive = Path(str(seed) + ".input.tar")
        snapshot = SealedInput(str(archive), digest, tuple(manifest), (), archive.stat().st_size)
        entry = {"kind": "section-marker", "outStart": 0, "outEnd": 2.5, "spec": {}}
        self.seal = ResolvedOverlaySeal(
            entry, {}, "", "compositions/section-marker.html", snapshot,
            "c" * 64, "mov", "mov", (1080, 1920), ("TEST metadata",), 2.5)
        self.resources = ResourceRequest(
            str(self.attempt), "attempt", "/TEST/docker", "/TEST/docker.sock",
            IMAGE_ID, "501:20")

    def _value(self, key: str | None = None, image_id: str = IMAGE_ID) -> dict:
        """Write fake bytes and a consistent historical proof, not real media."""
        key = key or self.seal.key
        path = Path(self.binding.cache_dir) / f"{key}.mov"
        path.write_bytes(b"rendered")
        path.chmod(0o600)
        return {"cached": False, "fmt": "mov", "fps": "30", "key": key,
                "kind": "section-marker", "path": str(path),
                "proof": build_full_proof(
                    path, key, image_id,
                    ProofInputs(self.seal.expected_copy, self.seal.snapshot))}

    @staticmethod
    def _rewrite_sidecar(value: dict) -> None:
        """Keep tampered metadata self-consistent so semantic checks are tested."""
        proof = value["proof"]
        disk = {key: nested for key, nested in proof.items() if key != "sidecar"}
        Path(proof["sidecar"]).write_text(json.dumps(disk), encoding="utf-8")
        Path(proof["sidecar"]).chmod(0o600)

    def _validate(self, value: dict) -> tuple[dict, dict]:
        """Read proof metadata directly; this does not authorize execution."""
        return _validated_result(
            json.dumps(value), self.binding, self.seal,
            (IMAGE_ID, CONTAINER_NAME, self.resources))
