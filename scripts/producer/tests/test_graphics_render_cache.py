"""Proof-before-cache-authority and concurrency regressions."""
from __future__ import annotations

import hashlib
import os
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from _common import pl  # noqa: F401
from graphics.render_cache import CacheRequest, materialize


def _proof(path: str) -> dict:
    if Path(path).read_bytes() != b"valid-media":
        raise RuntimeError("decode failed")
    sidecar = path + ".proof.json"
    Path(sidecar).write_bytes(b"proof")
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return {"sidecar": sidecar, "asset": {"sha256": digest}}


class RenderCacheTests(unittest.TestCase):
    def test_failed_candidate_never_becomes_cache_authority(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            request = CacheRequest(root, "a" * 40, "mov")
            renders = []

            def garbage(path: str) -> None:
                renders.append(path)
                Path(path).write_bytes(b"garbage")

            with self.assertRaisesRegex(RuntimeError, "decode failed"):
                materialize(request, garbage, _proof)
            output = os.path.join(root, f"{request.key}.mov")
            self.assertFalse(os.path.lexists(output))

            def valid(path: str) -> None:
                renders.append(path)
                Path(path).write_bytes(b"valid-media")

            path, cached, _ = materialize(request, valid, _proof)
            self.assertFalse(cached)
            self.assertEqual(Path(path).read_bytes(), b"valid-media")
            self.assertEqual(len(renders), 2)

    def test_existing_poison_is_quarantined_then_rerendered(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            request = CacheRequest(root, "b" * 40, "mov")
            output = os.path.join(root, f"{request.key}.mov")
            Path(output).write_bytes(b"garbage")

            def render(path: str) -> None:
                Path(path).write_bytes(b"valid-media")

            path, cached, _ = materialize(request, render, _proof)
            self.assertFalse(cached)
            self.assertEqual(Path(path).read_bytes(), b"valid-media")
            self.assertTrue(any(".rejected-" in name for name in os.listdir(root)))

    def test_valid_hit_skips_renderer(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            request = CacheRequest(root, "c" * 40, "mov")

            def render(path: str) -> None:
                Path(path).write_bytes(b"valid-media")

            materialize(request, render, _proof)
            path, cached, _ = materialize(
                request, lambda _: self.fail("renderer ran on proved hit"), _proof)
            self.assertTrue(cached)
            self.assertEqual(Path(path).read_bytes(), b"valid-media")

    def test_runtime_receipt_survives_cold_promotion_and_warm_proof(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            request = CacheRequest(root, "f" * 40, "mov")

            def render(path: str) -> None:
                Path(path).write_bytes(b"valid-media")
                Path(path + ".runtime.json").write_bytes(b"runtime")
                Path(path + ".input.tar").write_bytes(b"sealed-input")

            def prove(path: str) -> dict:
                self.assertEqual(Path(path + ".runtime.json").read_bytes(), b"runtime")
                result = _proof(path)
                result["runtimeAttestation"] = {"retained": True}
                return result

            cold, cached, _ = materialize(request, render, prove)
            self.assertFalse(cached)
            self.assertEqual(Path(cold + ".runtime.json").read_bytes(), b"runtime")
            self.assertEqual(Path(cold + ".input.tar").read_bytes(), b"sealed-input")
            warm, cached, _ = materialize(
                request, lambda _: self.fail("renderer ran"), prove)
            self.assertTrue(cached)
            self.assertEqual(warm, cold)

    def test_sixteen_concurrent_writers_render_once(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            request = CacheRequest(root, "d" * 40, "mov")
            count = 0
            count_lock = threading.Lock()

            def render(path: str) -> None:
                nonlocal count
                with count_lock:
                    count += 1
                time.sleep(0.02)
                Path(path).write_bytes(b"valid-media")

            with ThreadPoolExecutor(max_workers=16) as pool:
                results = list(pool.map(
                    lambda _: materialize(request, render, _proof), range(16)))
            self.assertEqual(count, 1)
            self.assertEqual(sum(not row[1] for row in results), 1)
            self.assertTrue(all(Path(row[0]).read_bytes() == b"valid-media"
                                for row in results))

    def test_symlink_or_hardlink_hit_never_becomes_authoritative(self) -> None:
        for link_kind in ("symlink", "hardlink"):
            with self.subTest(link_kind=link_kind), \
                    tempfile.TemporaryDirectory() as root:
                request = CacheRequest(root, "e" * 40, "mov")
                output = os.path.join(root, f"{request.key}.mov")
                outside = os.path.join(root, "outside.mov")
                Path(outside).write_bytes(b"valid-media")
                if link_kind == "symlink":
                    os.symlink(outside, output)
                else:
                    os.link(outside, output)

                def render(path: str) -> None:
                    Path(path).write_bytes(b"valid-media")

                path, cached, _ = materialize(request, render, _proof)
                self.assertFalse(cached)
                self.assertEqual(os.stat(path).st_nlink, 1)
                self.assertEqual(Path(outside).read_bytes(), b"valid-media")

    def test_candidate_swapped_after_proof_cannot_be_promoted(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            candidate = os.path.join(root, "candidate.mov")
            output = os.path.join(root, "output.mov")
            Path(candidate).write_bytes(b"valid-media")
            proof = _proof(candidate)
            Path(candidate).write_bytes(b"different-media")
            with self.assertRaisesRegex(RuntimeError, "media proof"):
                from graphics import render_cache
                render_cache._promote(candidate, output, proof)
            self.assertFalse(os.path.lexists(output))

    def test_cold_and_warm_cache_survive_restrictive_umask(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            request = CacheRequest(root, "9" * 40, "mov")

            def render(path: str) -> None:
                Path(path).write_bytes(b"valid-media")
                os.chmod(path, 0o600)

            def prove(path: str) -> dict:
                sidecar = path + ".proof.json"
                Path(sidecar).write_bytes(b"proof")
                os.chmod(sidecar, 0o600)
                digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
                return {"sidecar": sidecar, "asset": {"sha256": digest}}

            previous = os.umask(0o777)
            try:
                cold, cached, _ = materialize(request, render, prove)
                warm, warm_cached, _ = materialize(request, render, prove)
            finally:
                os.umask(previous)
            self.assertFalse(cached)
            self.assertTrue(warm_cached)
            self.assertEqual(cold, warm)
            self.assertEqual(os.stat(cold).st_mode & 0o777, 0o600)
            lock = os.path.join(root, f".{request.key}.lock")
            self.assertEqual(os.stat(lock).st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main(verbosity=2)
