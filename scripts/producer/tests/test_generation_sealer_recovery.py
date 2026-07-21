from __future__ import annotations

import unittest
from unittest import mock

from _common import pl  # noqa: F401
from _generation_sealer_fixture import SealerFixture, write
import headless.generation_sealer as sealer_module
import headless.generation_sealer_cleanup as cleanup_module
import headless.generation_sealer_final as final_module
from headless.generation_sealer import seal_generation
from headless.generation_sealer_types import GenerationSealError


class GenerationSealerRecoveryTests(unittest.TestCase):
    def test_crash_residue_recovers_before_a_fresh_install(self) -> None:
        for crash_label in ("payload-copied", "pending-sealed"):
            fixture = SealerFixture()

            def crash(label: str) -> None:
                if label == crash_label:
                    raise KeyboardInterrupt(label)

            try:
                with self.subTest(label=crash_label), mock.patch.object(
                    sealer_module, "_checkpoint", crash
                ):
                    with self.assertRaises(KeyboardInterrupt):
                        seal_generation(fixture.request())
                self.assertTrue(fixture.pending().exists())
                result = seal_generation(fixture.request())
                self.assertFalse(result.replayed)
                self.assertFalse(fixture.pending().exists())
            finally:
                fixture.close()

    def test_crash_after_install_recovers_as_exact_replay(self) -> None:
        fixture = SealerFixture()

        def crash(label: str) -> None:
            if label == "after-install":
                raise KeyboardInterrupt(label)

        try:
            with mock.patch.object(sealer_module, "_checkpoint", crash):
                with self.assertRaises(KeyboardInterrupt):
                    seal_generation(fixture.request())
            self.assertTrue(fixture.final().exists())
            self.assertTrue(seal_generation(fixture.request()).replayed)
        finally:
            fixture.close()

    def test_sealed_residue_installs_without_the_old_staging_path(
        self,
    ) -> None:
        fixture = SealerFixture()

        def crash(label: str) -> None:
            if label == "pending-sealed":
                raise KeyboardInterrupt(label)

        try:
            with mock.patch.object(sealer_module, "_checkpoint", crash):
                with self.assertRaises(KeyboardInterrupt):
                    seal_generation(fixture.request())
            fixture.staging.rename(fixture.root / "retired-staging")
            result = seal_generation(fixture.request())
            self.assertFalse(result.replayed)
            self.assertTrue(fixture.final().exists())
            self.assertFalse(fixture.pending().exists())
        finally:
            fixture.close()

    def test_crash_residue_cannot_be_rebound_to_a_different_commit(
        self,
    ) -> None:
        for crash_label, metadata_name in (
            ("payload-copied", ".seal-intent.json"),
            ("pending-sealed", "commit.json"),
        ):
            fixture = SealerFixture()

            def crash(label: str) -> None:
                if label == crash_label:
                    raise KeyboardInterrupt(label)

            try:
                with self.subTest(label=crash_label), mock.patch.object(
                    sealer_module, "_checkpoint", crash
                ):
                    with self.assertRaises(KeyboardInterrupt):
                        seal_generation(fixture.request())
                metadata = fixture.pending() / metadata_name
                self.assertEqual(metadata.read_bytes(), fixture.commit_json)
                changed_raw = b"different"
                (fixture.staging / "media/final.mp4").write_bytes(changed_raw)
                changed = fixture.changed_commit(
                    "media/final.mp4", changed_raw
                )
                with self.assertRaisesRegex(
                    GenerationSealError, "equivocation"
                ):
                    seal_generation(fixture.request(changed))
                self.assertEqual(metadata.read_bytes(), fixture.commit_json)
                self.assertTrue(fixture.pending().exists())
                self.assertFalse(fixture.final().exists())
            finally:
                fixture.close()

    def test_torn_uncommitted_intent_recovers_before_payload_copy(
        self,
    ) -> None:
        fixture = SealerFixture()

        def tear(fd: int, raw: bytes) -> None:
            final_module.os.write(fd, raw[:17])
            raise KeyboardInterrupt("torn-intent")

        try:
            with mock.patch.object(final_module, "_write_chunk", tear):
                with self.assertRaises(KeyboardInterrupt):
                    seal_generation(fixture.request())
            temporary = fixture.pending() / ".seal-intent.pending"
            self.assertEqual(temporary.read_bytes(), fixture.commit_json[:17])
            self.assertFalse(seal_generation(fixture.request()).replayed)
            self.assertFalse(fixture.pending().exists())
            self.assertTrue(fixture.final().exists())
        finally:
            fixture.close()

    def test_flushed_uncommitted_intent_cannot_be_rebound(self) -> None:
        fixture = SealerFixture()
        original = final_module._rename_noreplace

        def crash(parent: object, source: str, target: str) -> None:
            if source == ".seal-intent.pending":
                raise KeyboardInterrupt("intent-flushed-before-rename")
            original(parent, source, target)

        try:
            with mock.patch.object(
                final_module, "_rename_noreplace", side_effect=crash
            ):
                with self.assertRaises(KeyboardInterrupt):
                    seal_generation(fixture.request())
            temporary = fixture.pending() / ".seal-intent.pending"
            self.assertEqual(temporary.read_bytes(), fixture.commit_json)
            changed_raw = b"different"
            (fixture.staging / "media/final.mp4").write_bytes(changed_raw)
            changed = fixture.changed_commit("media/final.mp4", changed_raw)
            with self.assertRaisesRegex(GenerationSealError, "equivocation"):
                seal_generation(fixture.request(changed))
            self.assertEqual(temporary.read_bytes(), fixture.commit_json)
        finally:
            fixture.close()

    def test_cleanup_keeps_identity_until_payload_is_gone(self) -> None:
        fixture = SealerFixture()
        original = cleanup_module._unlink_opened
        interrupted = []

        def crash(parent: object, opened: object) -> None:
            original(parent, opened)
            if (
                opened.name not in cleanup_module._METADATA_NAMES
                and not interrupted
            ):
                interrupted.append(opened.name)
                raise KeyboardInterrupt("cleanup-after-payload-delete")

        try:
            self._leave_payload_residue(fixture)
            with mock.patch.object(
                cleanup_module, "_unlink_opened", side_effect=crash
            ):
                with self.assertRaises(KeyboardInterrupt):
                    seal_generation(fixture.request())
            self.assertTrue(interrupted)
            self.assertTrue((fixture.pending() / ".seal-intent.json").exists())
            result = seal_generation(fixture.request())
            self.assertFalse(result.replayed)
            self.assertTrue(fixture.final().exists())
        finally:
            fixture.close()

    @staticmethod
    def _leave_payload_residue(fixture: SealerFixture) -> None:
        def crash(label: str) -> None:
            if label == "payload-copied":
                raise KeyboardInterrupt(label)

        with mock.patch.object(sealer_module, "_checkpoint", crash):
            with unittest.TestCase().assertRaises(KeyboardInterrupt):
                seal_generation(fixture.request())

    def test_ordinary_failure_cleans_only_owned_pending_tree(self) -> None:
        fixture = SealerFixture()
        try:
            with mock.patch.object(
                sealer_module, "_checkpoint", side_effect=RuntimeError("fault")
            ):
                with self.assertRaises(GenerationSealError):
                    seal_generation(fixture.request())
            self.assertFalse(fixture.pending().exists())
            self.assertFalse(fixture.final().exists())
        finally:
            fixture.close()

    def test_unknown_crash_residue_is_preserved_and_blocks_recovery(
        self,
    ) -> None:
        for crash_label in ("payload-copied", "pending-sealed"):
            fixture = SealerFixture()

            def crash(label: str) -> None:
                if label == crash_label:
                    raise KeyboardInterrupt(label)

            try:
                with self.subTest(label=crash_label), mock.patch.object(
                    sealer_module, "_checkpoint", crash
                ):
                    with self.assertRaises(KeyboardInterrupt):
                        seal_generation(fixture.request())
                mode = fixture.pending().stat().st_mode & 0o777
                fixture.pending().chmod(0o700)
                write(fixture.pending() / "unknown", b"do-not-delete", 0o600)
                fixture.pending().chmod(mode)
                with self.assertRaises(GenerationSealError):
                    seal_generation(fixture.request())
                unknown = fixture.pending() / "unknown"
                self.assertEqual(unknown.read_bytes(), b"do-not-delete")
                self.assertEqual(
                    fixture.pending().stat().st_mode & 0o777, mode
                )
            finally:
                fixture.close()

    def test_pending_symlink_is_preserved_and_never_followed(self) -> None:
        fixture = SealerFixture()

        def crash(label: str) -> None:
            if label == "payload-copied":
                raise KeyboardInterrupt(label)

        try:
            with mock.patch.object(sealer_module, "_checkpoint", crash):
                with self.assertRaises(KeyboardInterrupt):
                    seal_generation(fixture.request())
            held = fixture.pending().with_name("held-pending")
            fixture.pending().rename(held)
            fixture.pending().symlink_to(held, target_is_directory=True)
            with self.assertRaises(GenerationSealError):
                seal_generation(fixture.request())
            self.assertTrue(fixture.pending().is_symlink())
            self.assertTrue(held.is_dir())
        finally:
            fixture.close()


if __name__ == "__main__":
    unittest.main()
