from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

PRODUCER_DIR = Path(__file__).resolve().parents[1]
TEST_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TEST_DIR))
sys.path.insert(0, str(PRODUCER_DIR))

from _render_lane_fixture import (  # noqa: E402
    IMAGE_ID,
    RenderLaneFixture,
)
from _render_lane_proof import ProofInputs, build_full_proof  # noqa: E402
from headless.process_runner import ProcessRequest  # noqa: E402
from headless.render_lane import (  # noqa: E402
    RENDERER_MODE,
    RenderExecutionPolicy,
    launch_overlay,
)
from headless.render_lane_cache import (  # noqa: E402
    CacheOwnershipError,
)


class RenderLaneAdversarialTests(RenderLaneFixture):
    def test_worker_result_cannot_escape_attempt_cache(self) -> None:
        outside = self.root / "outside.mov"
        outside.write_bytes(b"outside")
        result = {
            "cached": False,
            "fmt": "mov",
            "key": "a" * 64,
            "kind": "section-marker",
            "path": str(outside),
            "proof": {
                "kind": "section-marker",
                "asset": {
                    "sha256": hashlib.sha256(b"outside").hexdigest(),
                    "sizeBytes": 7,
                },
            },
        }
        completed = subprocess.CompletedProcess([], 0, json.dumps(result), "")
        with mock.patch("headless.render_lane.run_text", return_value=completed):
            with self.assertRaisesRegex(RuntimeError, "invalid result|escaped"):
                launch_overlay(
                    RenderExecutionPolicy(RENDERER_MODE),
                    self._request(),
                    self._runtime(),
                )

    def test_worker_result_symlink_inside_cache_is_rejected(self) -> None:
        def symlink_result(
            request: ProcessRequest,
        ) -> subprocess.CompletedProcess[str]:
            worker = json.loads(request.stdin_text)
            seal = self._sealed(worker)
            cache = Path(worker["cacheDir"])
            target = cache / ("b" * 64 + ".mov")
            target.write_bytes(b"rendered")
            target.chmod(0o600)
            alias = cache / (seal.key + ".mov")
            alias.symlink_to(target.name)
            result = {
                "cached": False,
                "fmt": "mov",
                "key": seal.key,
                "kind": "section-marker",
                "path": str(alias),
                "proof": {
                    "kind": "section-marker",
                    "asset": {
                        "sha256": hashlib.sha256(b"rendered").hexdigest(),
                        "sizeBytes": 8,
                    },
                },
            }
            return subprocess.CompletedProcess(
                request.command, 0, json.dumps(result), ""
            )

        with mock.patch("headless.render_lane.run_text", side_effect=symlink_result):
            with self.assertRaisesRegex(RuntimeError, "escaped"):
                launch_overlay(
                    RenderExecutionPolicy(RENDERER_MODE),
                    self._request(),
                    self._runtime(),
                )

    def test_worker_cache_directory_replacement_is_rejected(self) -> None:
        def replaced_cache(
            request: ProcessRequest,
        ) -> subprocess.CompletedProcess[str]:
            worker = json.loads(request.stdin_text)
            seal = self._sealed(worker)
            cache = Path(worker["cacheDir"])
            cache.rename(cache.parent / "graphics-cache-original")
            cache.mkdir(mode=0o700)
            os.chmod(cache, 0o700)
            path = cache / (seal.key + ".mov")
            path.write_bytes(b"rendered")
            path.chmod(0o600)
            result = {
                "cached": False,
                "fmt": "mov",
                "key": seal.key,
                "kind": "section-marker",
                "path": str(path),
                "proof": build_full_proof(
                    path,
                    seal.key,
                    IMAGE_ID,
                    ProofInputs(seal.expected_copy, seal.snapshot),
                ),
            }
            return subprocess.CompletedProcess(
                request.command, 0, json.dumps(result), ""
            )

        with mock.patch(
            "headless.render_lane.run_text", side_effect=replaced_cache
        ), self.assertRaisesRegex(
            CacheOwnershipError, "cache directory identity changed"
        ):
            launch_overlay(
                RenderExecutionPolicy(RENDERER_MODE), self._request(), self._runtime()
            )

    def test_worker_result_must_match_request_path_and_media_proof(self) -> None:
        cases = (
            ("empty", b"", "expected", "mov", "section-marker", None),
            ("wrong-name", b"rendered", "wrong", "mov", "section-marker", None),
            ("wrong-format", b"rendered", "expected", "mp4", "section-marker", None),
            ("wrong-kind", b"rendered", "expected", "mov", "wrong-kind", None),
            (
                "wrong-proof",
                b"rendered",
                "expected",
                "mov",
                "section-marker",
                "0" * 64,
            ),
        )
        for label, media, name_mode, fmt, kind, forced_digest in cases:

            def malformed(
                request: ProcessRequest,
            ) -> subprocess.CompletedProcess[str]:
                worker = json.loads(request.stdin_text)
                seal = self._sealed(worker)
                extension = fmt if label == "wrong-format" else "mov"
                basename = (
                    f"{seal.key}.{extension}"
                    if name_mode == "expected"
                    else "wrong-name.mov"
                )
                path = Path(worker["cacheDir"]) / basename
                path.write_bytes(media)
                path.chmod(0o600)
                digest = forced_digest or hashlib.sha256(media).hexdigest()
                result = {
                    "cached": False,
                    "fmt": fmt,
                    "key": seal.key,
                    "kind": kind,
                    "path": str(path),
                    "proof": {
                        "kind": kind,
                        "asset": {"sha256": digest, "sizeBytes": len(media)},
                    },
                }
                return subprocess.CompletedProcess(
                    request.command, 0, json.dumps(result), ""
                )

            with self.subTest(label=label), mock.patch(
                "headless.render_lane.run_text", side_effect=malformed
            ), self.assertRaises(RuntimeError):
                launch_overlay(
                    RenderExecutionPolicy(RENDERER_MODE),
                    self._request(),
                    self._runtime(),
                )

    def test_self_consistent_wrong_copy_proof_is_rejected(self) -> None:
        def wrong_copy(request: ProcessRequest) -> subprocess.CompletedProcess[str]:
            worker = json.loads(request.stdin_text)
            seal = self._sealed(worker)
            path = Path(worker["cacheDir"]) / (seal.key + ".mov")
            path.write_bytes(b"rendered")
            path.chmod(0o600)
            result = {
                "cached": False,
                "fmt": "mov",
                "key": seal.key,
                "kind": "section-marker",
                "path": str(path),
                "proof": build_full_proof(
                    path,
                    seal.key,
                    IMAGE_ID,
                    ProofInputs(("WRONG",), seal.snapshot),
                ),
            }
            return subprocess.CompletedProcess(
                request.command, 0, json.dumps(result), ""
            )

        with mock.patch(
            "headless.render_lane.run_text", side_effect=wrong_copy
        ), self.assertRaisesRegex(RuntimeError, "copy"):
            launch_overlay(
                RenderExecutionPolicy(RENDERER_MODE), self._request(), self._runtime()
            )
