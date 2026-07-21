from __future__ import annotations

import json
import multiprocessing
import unittest
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from unittest import mock

from _common import pl  # noqa: F401
from _generation_sealer_fixture import SealerFixture, canonical
import headless.generation_sealer as sealer_module
from headless.generation_reader import read_current_generation
from headless.generation_sealer import seal_generation
from headless.generation_sealer_types import GenerationSealRequestV1


def _process_seal(
    request: GenerationSealRequestV1, queue: Any, rendezvous: Any
) -> None:
    rendezvous.wait(timeout=3)
    try:
        queue.put(("ok", seal_generation(request).replayed))
    except Exception as exc:  # pragma: no cover - reported to the parent
        queue.put((type(exc).__name__, str(exc)))


class GenerationSealerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = SealerFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def test_fresh_inode_generation_is_sealed_but_not_published(self) -> None:
        fixture = self.fixture
        source_inodes = {
            relative: (fixture.staging / relative).stat().st_ino
            for relative in fixture.files
        }
        result = seal_generation(fixture.request())
        self.assertFalse(result.replayed)
        self.assertEqual(fixture.final().stat().st_mode & 0o777, 0o500)
        self.assertFalse((fixture.authority / "CURRENT").exists())
        self.assertFalse((fixture.authority / ".publish.mutex").exists())
        self.assertFalse((fixture.authority / "FENCE").exists())
        self.assertFalse(fixture.pending().exists())
        for relative, expected in fixture.files.items():
            final = fixture.final() / relative
            self.assertEqual(final.read_bytes(), expected)
            self.assertEqual(final.stat().st_mode & 0o777, 0o400)
            self.assertNotEqual(final.stat().st_ino, source_inodes[relative])
        self.assertEqual(
            (fixture.final() / "commit.json").read_bytes(), fixture.commit_json
        )
        self.assertEqual(
            (fixture.final() / "commit.json").stat().st_mode & 0o777, 0o400
        )

    def test_result_is_compatible_with_existing_pinned_reader(self) -> None:
        fixture = self.fixture
        seal_generation(fixture.request())
        fixture.publish_for_reader()
        with read_current_generation(
            str(fixture.authority), str(fixture.destination)
        ) as resolved:
            self.assertEqual(
                resolved.commit.document_json, fixture.commit_json
            )
            self.assertEqual(set(resolved.materialized), set(fixture.files))

    def test_exact_replay_does_not_need_the_old_staging_path(self) -> None:
        fixture = self.fixture
        first = seal_generation(fixture.request())
        fixture.staging.rename(fixture.root / "retired-staging")
        replay = seal_generation(fixture.request())
        self.assertFalse(first.replayed)
        self.assertTrue(replay.replayed)
        self.assertEqual(first.commit_digest, replay.commit_digest)

    def test_commit_is_created_after_payload_and_before_read_only_seal(
        self,
    ) -> None:
        fixture = self.fixture
        observed = []

        def inspect(label: str) -> None:
            if label == "payload-copied":
                observed.append(
                    (label, fixture.pending().joinpath("commit.json").exists())
                )
                media = fixture.pending() / "media/final.mp4"
                observed.append(("payload-mode", media.stat().st_mode & 0o777))
            if label == "pending-sealed":
                commit = fixture.pending() / "commit.json"
                observed.append((label, commit.exists()))
                observed.append(("commit-mode", commit.stat().st_mode & 0o777))

        with mock.patch.object(sealer_module, "_checkpoint", inspect):
            seal_generation(fixture.request())
        self.assertEqual(
            observed,
            [
                ("payload-copied", False),
                ("payload-mode", 0o600),
                ("pending-sealed", True),
                ("commit-mode", 0o400),
            ],
        )

    def test_concurrent_same_commit_is_one_install_and_one_replay(
        self,
    ) -> None:
        request = self.fixture.request()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(seal_generation, (request, request)))
        self.assertEqual(
            sorted(result.replayed for result in results), [False, True]
        )
        self.assertEqual(len({result.commit_digest for result in results}), 1)
        self.assertFalse(self.fixture.pending().exists())

    def test_concurrent_processes_are_one_install_and_one_replay(self) -> None:
        context = multiprocessing.get_context("fork")
        queue = context.Queue()
        rendezvous = context.Barrier(2)
        workers = [
            context.Process(
                target=_process_seal,
                args=(self.fixture.request(), queue, rendezvous),
            )
            for _index in range(2)
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=10)
            self.assertEqual(worker.exitcode, 0)
        outcomes = [queue.get(timeout=2) for _index in workers]
        self.assertEqual(sorted(outcomes), [("ok", False), ("ok", True)])
        self.assertTrue(self.fixture.final().exists())
        self.assertFalse(self.fixture.pending().exists())

    def test_authority_binding_rejects_later_authority_equivocation(
        self,
    ) -> None:
        fixture = self.fixture
        seal_generation(fixture.request())
        document = json.loads(fixture.commit_json)
        document["authorityId"] = "different-authority"
        before = (fixture.final() / "commit.json").read_bytes()
        with self.assertRaisesRegex(RuntimeError, "safely sealed"):
            seal_generation(fixture.request(canonical(document)))
        self.assertEqual(
            (fixture.final() / "commit.json").read_bytes(), before
        )

    def test_result_is_path_free_and_non_authorizing(self) -> None:
        result = seal_generation(self.fixture.request())
        self.assertEqual(
            set(vars(result)),
            {"commit_digest", "generation_id", "replayed"},
        )
        authority = json.loads(
            (self.fixture.authority / "authority.json").read_bytes()
        )
        self.assertEqual(authority["authorityId"], "authority-mp4-v1")
        self.assertEqual(
            (self.fixture.authority / ".generation-seal.lock").stat().st_mode
            & 0o777,
            0o600,
        )


if __name__ == "__main__":
    unittest.main()
