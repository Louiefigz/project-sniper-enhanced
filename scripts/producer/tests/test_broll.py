"""broll tests (split from selftest.py)."""
import unittest

from _common import *  # noqa: F401,F403
from _broll_pool_authority_fixture import build_pool_authority
from broll.pool_admission import PoolAuthority, open_pool


class BrollInsertTests(unittest.TestCase):
    """broll_insert.py — receipts replace frames, never the speech audio (R17)."""

    @classmethod
    def setUpClass(cls) -> None:
        if not _HAVE_FFMPEG:
            raise unittest.SkipTest("ffmpeg not on PATH")
        cls.dir = tempfile.mkdtemp(prefix="selftest-broll-")
        cls.base = os.path.join(cls.dir, "base.mp4")
        bi.run_ff(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                   "-f", "lavfi", "-i", "color=c=gray:s=640x360:d=8:r=30",
                   "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=48000:duration=8",
                   "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                   "-c:a", "aac", "-b:a", "128k", "-shortest", cls.base])
        asset = os.path.join(cls.dir, "receipt.mp4")
        bi.run_ff(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                   "-f", "lavfi", "-i", "color=c=red:s=640x360:d=4:r=30",
                   "-c:v", "libx264", "-preset", "veryfast",
                   "-pix_fmt", "yuv420p", asset])
        cls.manifest = {"_path": os.path.join(cls.dir, "m.json"),
                        "broll": [{"id": "b-1", "path": "receipt.mp4",
                                   "kind": "video", "duration": 4.0}]}
        cls.out = os.path.join(cls.dir, "out.mp4")
        inserts = bi.resolve_assets(
            bi.parse_inserts([{"assetId": "b-1", "outStart": 2.0,
                               "outEnd": 4.0}], 8.0, 5.0), cls.manifest)
        cls.result = bi.apply_broll_inserts(cls.base, inserts, cls.out)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_insert_validation_rejects_bad_input(self) -> None:
        with self.assertRaises(ValueError):     # overlapping windows
            bi.parse_inserts([{"assetId": "b-1", "outStart": 2.0, "outEnd": 4.0},
                              {"assetId": "b-1", "outStart": 3.5, "outEnd": 5.0}],
                             8.0, 5.0)
        with self.assertRaises(ValueError):     # inside the 0.5s edge margin
            bi.parse_inserts([{"assetId": "b-1", "outStart": 0.2,
                               "outEnd": 2.0}], 8.0, 5.0)
        with self.assertRaises(ValueError):     # under the 0.8s minimum
            bi.parse_inserts([{"assetId": "b-1", "outStart": 2.0,
                               "outEnd": 2.5}], 8.0, 5.0)
        with self.assertRaises(ValueError):     # asset too short: 3+2 > 4s
            bi.resolve_assets(bi.parse_inserts(
                [{"assetId": "b-1", "outStart": 2.0, "outEnd": 4.0,
                  "assetStart": 3.0}], 8.0, 5.0), self.manifest)
        with self.assertRaises(ValueError):     # assetId not in manifest
            bi.resolve_assets(bi.parse_inserts(
                [{"assetId": "ghost", "outStart": 2.0, "outEnd": 4.0}],
                8.0, 5.0), self.manifest)

    def test_frame_count_and_duration_preserved(self) -> None:
        self.assertEqual(self.result["inFrames"], self.result["outFrames"])
        self.assertEqual(bi.probe_video_frames(self.out),
                         bi.probe_video_frames(self.base))
        self.assertLess(abs(bi.probe_duration(self.out)
                            - bi.probe_duration(self.base)), HALF_FRAME_S)

    def test_audio_stream_copied_bit_identical(self) -> None:
        md5s = [bi.run_ff(["ffmpeg", "-v", "error", "-i", p, "-map", "0:a:0",
                           "-c", "copy", "-f", "md5", "-"]).strip()
                for p in (self.base, self.out)]
        self.assertEqual(md5s[0], md5s[1])

    def test_replacement_lands_inside_window_only(self) -> None:
        # Red asset (YAVG ~76) replaces the gray base (~126) at 3.0s (frame 90)
        # and only there — 1.0s (frame 30) and 5.0s (frame 150) stay base-gray.
        self.assertLess(_frame_yavg(self.out, 90), 100.0)
        self.assertLess(abs(_frame_yavg(self.out, 30)
                            - _frame_yavg(self.base, 30)), 8.0)
        self.assertLess(abs(_frame_yavg(self.out, 150)
                            - _frame_yavg(self.base, 150)), 8.0)


class BrollPoolTests(unittest.TestCase):
    """broll_pool — pool cataloging + R17 receipt resolution (tags only).

    Naming is NEVER load-bearing: the fixture clip is deliberately named
    youtube.mp4 and must resolve nothing until the brain tags it.
    """

    @classmethod
    def setUpClass(cls) -> None:
        if not _HAVE_FFMPEG:
            raise unittest.SkipTest("ffmpeg not on PATH")
        cls.root = tempfile.mkdtemp(prefix="selftest-pool-")
        cls.src = os.path.join(cls.root, "src.mp4")
        cls.manifests = {}
        bp.run_command(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                        "-f", "lavfi", "-i", "color=c=blue:s=320x180:d=2:r=30",
                        "-c:v", "libx264", "-preset", "veryfast",
                        "-pix_fmt", "yuv420p", cls.src])

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.root, ignore_errors=True)

    def _mk_pool(self, *rels: str) -> Path:
        """A fresh pool dir with copies of the fixture clip at the rel paths."""
        pool = Path(tempfile.mkdtemp(dir=self.root)) / "broll"
        for rel in rels:
            dst = pool / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(self.src, dst)
        self._admit(pool)
        return pool

    def _admit(self, pool: Path) -> PoolAuthority:
        manifest_path, authority = build_pool_authority(pool)
        self.manifests[str(pool)] = manifest_path
        return authority

    def _authority(self, pool: Path) -> PoolAuthority:
        return open_pool(pool, self.manifests[str(pool)])

    def _scan(self, pool: Path) -> list[dict]:
        with contextlib.redirect_stdout(io.StringIO()):
            return bp.scan_pool(self._authority(pool))

    def _annotate(self, pool: Path, rid: str, tags: list[str]) -> dict:
        return bp.annotate(
            self._authority(pool), rid, tags, "seen: fixture clip")

    def test_scan_idempotency_and_mtime_reset(self) -> None:
        pool = self._mk_pool("screen-recordings/youtube.mp4")
        (rec,) = self._scan(pool)
        self.assertEqual(rec["id"], "screen-recordings-youtube")
        self.assertFalse(rec["cataloged"])
        self.assertEqual(len(rec["frames"]), 3)          # 15/50/85% settled frames
        self.assertTrue(all((pool / f).exists() for f in rec["frames"]))
        self._annotate(pool, rec["id"], ["cartoons", "animation"])
        (again,) = self._scan(pool)                      # idempotent re-scan
        self.assertTrue(again["cataloged"])              # vision fields preserved
        self.assertEqual(again["tags"], ["animation", "cartoons"])
        self.assertEqual(again["id"], rec["id"])
        late = pool / "screen-recordings" / "late.mp4"
        shutil.copy(self.src, late)
        with self.assertRaisesRegex(RuntimeError, "re-run canonical ingest"):
            self._authority(pool)
        self._admit(pool)
        rescanned = self._scan(pool)
        self.assertEqual(len(rescanned), 2)
        self.assertEqual(
            sum(not row["cataloged"] for row in rescanned), 1)
        path = pool / "screen-recordings/youtube.mp4"
        path.write_bytes(b"untrusted replacement after admission")
        stable = self._scan(pool)
        reviewed = next(row for row in stable if row["id"] == rec["id"])
        self.assertTrue(reviewed["cataloged"])
        self.assertEqual(len(reviewed["frames"]), 3)

    def test_annotate_round_trip(self) -> None:
        pool = self._mk_pool("screen-recordings/clip.mp4")
        (rec,) = self._scan(pool)
        authority = self._authority(pool)
        bp.annotate(authority, rec["id"],
                    [" YouTube", "Channel ", "screen-recording"],
                    "his channel page, subscriber count visible")
        (stored,) = bp.load_catalog(authority)
        self.assertTrue(stored["cataloged"])
        self.assertEqual(stored["tags"],                 # lowercased, sorted tokens
                         ["channel", "screen-recording", "youtube"])
        self.assertEqual(stored["descriptionSource"], "vision")
        self.assertRaises(
            ValueError, bp.annotate, authority, "ghost-id", ["x"], "d")
        self.assertRaises(
            ValueError, bp.annotate, authority, rec["id"], ["  "], "d")
        self.assertRaises(
            ValueError, bp.annotate, authority, rec["id"], ["x"], " ")

    def test_manifest_contract_feeds_broll_insert(self) -> None:
        pool = self._mk_pool("screen-recordings/clip.mp4")
        (rec,) = self._scan(pool)
        authority = self._authority(pool)
        self.assertEqual(bp.manifest_entries(bp.load_catalog(authority)), [])
        self._annotate(pool, rec["id"], ["youtube", "channel"])
        entries = bp.manifest_entries(bp.load_catalog(authority))
        self.assertEqual([e["id"] for e in entries], [rec["id"]])
        self.assertEqual(entries[0]["kind"], "video")
        self.assertAlmostEqual(entries[0]["duration"], 2.0, delta=0.2)
        manifest = {"_path": str(pool / "m.json"), "broll": entries}
        inserts = bi.resolve_assets(                     # the real consumer
            bi.parse_inserts([{"assetId": rec["id"], "outStart": 2.0,
                               "outEnd": 3.5}], 8.0, 5.0), manifest)
        self.assertEqual(inserts[0].path, entries[0]["path"])
        self.assertIn(".sniper-external-media", inserts[0].path)
        with self.assertRaises(ValueError):              # unknown id still hard-fails
            bi.resolve_assets(bi.parse_inserts(
                [{"assetId": "ghost", "outStart": 2.0, "outEnd": 3.5}],
                8.0, 5.0), manifest)

    def test_resolver_exact_multi_zero(self) -> None:
        pool = self._mk_pool("a/a.mp4", "a/b.mp4", "a/c.mp4")
        recs = self._scan(pool)
        by_path = {
            r["originalPath"].rsplit("/", 1)[-1]: r["id"] for r in recs
        }
        self._annotate(pool, by_path["a.mp4"], ["youtube", "channel"])
        self._annotate(pool, by_path["b.mp4"], ["website", "laptop"])
        self._annotate(pool, by_path["c.mp4"], ["youtube", "cartoons"])
        rows = [{"assetId": None, "needsOperator": True, "note": "receipt: website"},
                {"assetId": None, "needsOperator": True, "note": "receipt: YouTube"},
                {"assetId": None, "needsOperator": True, "note": "receipt: podcast"},
                {"assetId": None, "needsOperator": True,
                 "note": "receipt: YouTube channel"}]
        concepts = [{"assetId": None, "needsOperator": True,
                     "note": "concept-stock: youtube"}]
        proposal = {"brollReceipts": rows, "brollConcept": concepts}
        out = bp.resolve_receipts(
            proposal, bp.load_catalog(self._authority(pool)))
        exact, multi, zero, alltok = out["brollReceipts"]
        self.assertEqual(exact["assetId"], by_path["b.mp4"])   # exactly one hit
        self.assertFalse(exact["needsOperator"])
        self.assertIn("resolved from pool", exact["note"])
        self.assertIsNone(multi["assetId"])              # 2 hits: stays operator
        self.assertTrue(multi["needsOperator"])
        self.assertNotIn("resolved", multi["note"])
        self.assertIsNone(zero["assetId"])               # 0 hits: no fuzzy fallback
        self.assertEqual(alltok["assetId"], by_path["a.mp4"])  # ALL tokens required
        self.assertEqual(out["brollConcept"], concepts)  # concept never auto-resolved
        self.assertIsNone(rows[0]["assetId"])            # input rows not mutated

    def test_naming_never_load_bearing(self) -> None:
        pool = self._mk_pool("archive/youtube.mp4")
        (rec,) = self._scan(pool)
        self._annotate(pool, rec["id"], ["cartoons", "animation"])  # NO youtube tag
        proposal = {"brollReceipts": [
            {"assetId": None, "needsOperator": True, "note": "receipt: YouTube"},
            {"assetId": None, "needsOperator": True, "note": "receipt: cartoons"}]}
        out = bp.resolve_receipts(
            proposal, bp.load_catalog(self._authority(pool)))
        named, tagged = out["brollReceipts"]
        self.assertIsNone(named["assetId"])              # filename resolves NOTHING
        self.assertTrue(named["needsOperator"])
        self.assertEqual(tagged["assetId"], rec["id"])   # tags are the only currency

    def test_mutable_original_never_changes_admitted_catalog(self) -> None:
        # After admission, touching the mutable original cannot replace the
        # reviewed snapshot or invalidate its vision verdict.
        pool = self._mk_pool("a/clip.mp4")
        (rec,) = self._scan(pool)
        self._annotate(pool, rec["id"], ["youtube"])
        path = pool / "a/clip.mp4"
        os.utime(path, (path.stat().st_atime, path.stat().st_mtime + 5))
        self._scan(pool)  # admitted snapshot is unchanged; annotations remain
        out = bp.resolve_receipts(
            {"brollReceipts": [{"assetId": None, "needsOperator": True,
                                "note": "receipt: YouTube"}]},
            bp.load_catalog(self._authority(pool)))
        self.assertEqual(out["brollReceipts"][0]["assetId"], rec["id"])

if __name__ == "__main__":
    unittest.main(verbosity=2)
