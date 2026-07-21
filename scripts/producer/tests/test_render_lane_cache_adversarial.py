from __future__ import annotations

import contextlib
import json
import os
import stat
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from unittest import mock

PRODUCER_DIR = Path(__file__).resolve().parents[1]
TEST_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TEST_DIR))
sys.path.insert(0, str(PRODUCER_DIR))

from _render_lane_fixture import (  # noqa: E402
    CONTAINER_NAME,
    IMAGE_ID,
    NEXT_CONTAINER_NAME,
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
    prepare_attempt_cache,
)


class RenderLaneCacheAdversarialTests(RenderLaneFixture):
    def test_second_launch_accepts_only_prior_removed_container_proof(self) -> None:
        request = self._request()
        launches = 0

        def miss_then_hit(
            process_request: ProcessRequest,
        ) -> subprocess.CompletedProcess[str]:
            nonlocal launches
            launches += 1
            if launches == 1:
                return self._fake_success(process_request)
            worker = json.loads(process_request.stdin_text)
            seal = self._sealed(worker)
            path = Path(worker["cacheDir"]) / (seal.key + ".mov")
            result = {
                "cached": True,
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
                process_request.command, 0, json.dumps(result), ""
            )

        names = iter((CONTAINER_NAME, NEXT_CONTAINER_NAME))

        @contextlib.contextmanager
        def sequenced_lease(_resource: object) -> Iterator[str]:
            yield next(names)

        with mock.patch(
            "headless.render_lane.container_lease", side_effect=sequenced_lease
        ), mock.patch(
            "headless.render_lane.removed_containers", return_value=(CONTAINER_NAME,)
        ), mock.patch(
            "headless.render_lane.run_text", side_effect=miss_then_hit
        ):
            first = launch_overlay(
                RenderExecutionPolicy(RENDERER_MODE), request, self._runtime()
            )
            second = launch_overlay(
                RenderExecutionPolicy(RENDERER_MODE), request, self._runtime()
            )
        self.assertFalse(first["result"]["cached"])
        self.assertTrue(second["result"]["cached"])

        with mock.patch(
            "headless.render_lane.removed_containers", return_value=()
        ), mock.patch(
            "headless.render_lane.run_text", side_effect=miss_then_hit
        ), self.assertRaisesRegex(
            RuntimeError, "registered resource"
        ):
            launch_overlay(
                RenderExecutionPolicy(RENDERER_MODE), request, self._runtime()
            )

    def test_symlink_and_wrong_mode_cache_fail_closed(self) -> None:
        request = self._request()
        identity = (
            request.attempt_id,
            request.request.request_digest,
            request.build_digest,
            IMAGE_ID,
        )
        alias = self.root / "attempt-alias"
        alias.symlink_to(self.attempt, target_is_directory=True)
        with self.assertRaisesRegex(CacheOwnershipError, "symlink-free"):
            prepare_attempt_cache(str(alias), identity)
        binding = prepare_attempt_cache(str(self.attempt), identity)
        os.chmod(binding.cache_dir, 0o755)
        with self.assertRaisesRegex(CacheOwnershipError, "0700"):
            prepare_attempt_cache(str(self.attempt), identity)

    def test_restrictive_umask_cannot_weaken_new_cache_receipt(self) -> None:
        attempt = self.root / "umask-attempt"
        attempt.mkdir(mode=0o700)
        os.chmod(attempt, 0o700)
        request = self._request()
        identity = (
            "umask-attempt",
            request.request.request_digest,
            request.build_digest,
            IMAGE_ID,
        )
        previous = os.umask(0o777)
        try:
            binding = prepare_attempt_cache(str(attempt), identity)
        finally:
            os.umask(previous)
        owner = Path(binding.cache_dir) / ".owner.json"
        self.assertEqual(stat.S_IMODE(owner.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(Path(binding.cache_dir).stat().st_mode), 0o700)
        self.assertEqual(prepare_attempt_cache(str(attempt), identity), binding)
