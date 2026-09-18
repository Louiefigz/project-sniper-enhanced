"""Native admission: parity with the container probe's code, and hostile inputs.

Parity runs the container's own ``NODE_PROBE`` JavaScript (paths rewritten, run
natively, no Docker) and the native Python port on the same files with the same
ffmpeg, and requires identical accept/reject outcomes and identical facts.
Hostile inputs go through the production ``admit_external_media`` entry.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

from _native_media_fixture import FONT, HAVE_NATIVE, DecoyListener, ffmpeg, valid_mp4
from headless.admission_receipt import validate_admission_receipt
from headless.external_media_probe import admit_external_media
from headless.external_media_probe_native import probe_facts, special_facts
from headless.external_media_probe_policy import NODE_PROBE, MediaProbeLimits
from headless.native_media_sandbox import JailRejection, verified_runtime

NODE = shutil.which("node")
LIMITS = MediaProbeLimits()


def _node_probe(path: Path, scratch: Path, limits: MediaProbeLimits) -> dict:
    """The container's probe code, verbatim except for its fixed container paths."""
    runtime = verified_runtime()
    script = (NODE_PROBE.replace("'/input/media'", json.dumps(str(path)))
              .replace("'/scratch/result.json'", json.dumps(str(scratch / "result.json")))
              .replace("'/usr/bin/ffprobe'", json.dumps(runtime.ffprobe))
              .replace("'/usr/bin/ffmpeg'", json.dumps(runtime.ffmpeg))
              .replace("setTimeout(()=>{},30000);", ""))
    subprocess.run([NODE, "-e", script, *[str(value) for value in asdict(limits).values()]],
                   capture_output=True, timeout=120, check=True)
    return json.loads((scratch / "result.json").read_text())


def _native(path: Path, limits: MediaProbeLimits) -> dict:
    """The native port's facts or its rejection code, without the jail wrapper."""
    runtime = verified_runtime()
    try:
        special = special_facts(str(path), limits)
        if special is not None:
            return {"ok": True, "facts": special}
        from headless.native_media_sandbox import JailLimits, run_decoder
        done = run_decoder(runtime, runtime.ffprobe, ("-v", "error", "-show_streams", "-show_format", "-of", "json",
                                                      str(path)), (str(path), JailLimits(10, 10)))
        facts = probe_facts(json.loads(done.stdout), limits)
        run_decoder(runtime, runtime.ffmpeg, ("-nostdin", "-v", "error", "-xerror", "-threads", "4", "-i", str(path),
                                              "-map", "0:v?", "-map", "0:a?", "-fps_mode", "vfr", "-f", "null", "-"),
                    (str(path), JailLimits(120, 500)))
        return {"ok": True, "facts": facts}
    except JailRejection as error:
        return {"ok": False, "code": error.code}


def _corpus(root: Path) -> dict[str, Path]:
    """Generated files covering every probe branch."""
    files = {"h264-aac.mp4": valid_mp4(root / "h264-aac.mp4"), "font.ttf": root / "font.ttf",
             "safe.svg": root / "safe.svg", "malformed.bin": root / "malformed.bin"}
    shutil.copyfile(FONT, files["font.ttf"])
    files["safe.svg"].write_text('<svg viewBox="0 0 64 32" xmlns="http://www.w3.org/2000/svg"><rect/></svg>')
    files["malformed.bin"].write_bytes(b"not-media" * 10)
    ffmpeg("-f", "lavfi", "-i", "color=c=red:size=96x64", "-frames:v", "1", str(root / "still.png"))
    ffmpeg("-f", "lavfi", "-i", "sine=duration=1", str(root / "tone.wav"))
    ffmpeg("-f", "lavfi", "-i", "testsrc2=size=160x90:rate=25:duration=1", "-c:v", "ffv1", str(root / "ffv1.mkv"))
    ffmpeg("-f", "lavfi", "-i", "color=size=8194x2:rate=1:duration=1", "-c:v", "rawvideo", str(root / "wide.nut"))
    data = files["h264-aac.mp4"].read_bytes()
    (root / "truncated.mp4").write_bytes(data[:len(data) // 3])
    for name in ("still.png", "tone.wav", "ffv1.mkv", "wide.nut", "truncated.mp4"):
        files[name] = root / name
    return files


@unittest.skipUnless(HAVE_NATIVE and NODE, "needs macOS, ffmpeg and node")
class ContainerProbeParityTests(unittest.TestCase):
    def test_native_port_matches_container_probe_code(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            for name, path in _corpus(root).items():
                scratch = root / f"scratch-{name}"
                scratch.mkdir()
                container, native = _node_probe(path, scratch, LIMITS), _native(path, LIMITS)
                with self.subTest(name=name):
                    self.assertEqual(container["ok"], native["ok"], (container, native))
                    if container["ok"]:
                        self.assertEqual(container["facts"], native["facts"])
                    elif container["code"].endswith("_LIMIT") or container["code"].startswith("SVG_"):
                        self.assertEqual(container["code"], native["code"])


@unittest.skipUnless(HAVE_NATIVE, "needs macOS and ffmpeg")
class NativeAdmissionHostileInputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _admit(self, path: Path, limits: MediaProbeLimits = LIMITS) -> dict:
        store = self.root / f"store-{path.name}"
        store.mkdir(exist_ok=True)
        return admit_external_media(str(path), str(store), limits)

    def _rejects(self, path: Path, pattern: str, limits: MediaProbeLimits = LIMITS) -> None:
        with self.assertRaisesRegex(RuntimeError, pattern):
            self._admit(path, limits)

    def test_valid_media_receipt_is_attested_and_readable(self) -> None:
        receipt = self._admit(valid_mp4(self.root / "valid.mp4"))
        limits, decoded = validate_admission_receipt(receipt)
        self.assertEqual(decoded["facts"]["mediaKind"], "timed-media")
        self.assertEqual([run["decoder"] for run in receipt["isolation"]["decoderRuns"]],
                         [receipt["runtime"]["tools"]["ffprobe"]["path"], receipt["runtime"]["tools"]["ffmpeg"]["path"]])

    def test_playlist_that_fetches_the_network_is_rejected_without_a_connection(self) -> None:
        decoy = DecoyListener()
        try:
            playlist = self.root / "playlist.mp4"
            playlist.write_text(f"#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXTINF:1,\nhttp://127.0.0.1:{decoy.port}/s.ts\n"
                                "#EXT-X-ENDLIST\n")
            self._rejects(playlist, "decode rejected")
        finally:
            decoy.close()
        self.assertEqual(decoy.connections, 0)

    def test_concat_list_cannot_read_a_sibling_file(self) -> None:
        store = self.root / "store-list.ffconcat"
        store.mkdir()
        valid_mp4(store / "sibling.mp4")
        listing = self.root / "list.ffconcat"
        listing.write_text("ffconcat version 1.0\nfile 'sibling.mp4'\n")
        with self.assertRaisesRegex(RuntimeError, "decode rejected"):
            admit_external_media(str(listing), str(store), LIMITS)

    def test_active_or_remote_svg_is_rejected(self) -> None:
        for index, body in enumerate(('<svg width="9" height="9"><script>alert(1)</script></svg>',
                                      '<svg width="9" height="9"><image href="https://example.com/x.png"/></svg>',
                                      '<svg width="9" height="9" onload="x()"></svg>')):
            svg = self.root / f"active-{index}.svg"
            svg.write_text(body)
            self._rejects(svg, "SVG_ACTIVE_CONTENT")

    def test_font_with_out_of_range_table_is_rejected(self) -> None:
        data = bytearray(FONT.read_bytes()[:4096])
        font = self.root / "cut.ttf"
        font.write_bytes(bytes(data))
        self._rejects(font, "FONT_TABLE")

    def test_malformed_truncated_and_corrupted_media_are_rejected(self) -> None:
        source = valid_mp4(self.root / "source.mp4", seconds=3).read_bytes()
        cases = {"malformed.mp4": b"not-media", "truncated.mp4": source[:len(source) // 3],
                 "corrupt.mp4": source[:len(source) // 2] + bytes(4096) + source[len(source) // 2 + 4096:]}
        for name, payload in cases.items():
            (self.root / name).write_bytes(payload)
            self._rejects(self.root / name, "decode rejected")

    def test_metadata_ceilings_reject_before_decode(self) -> None:
        ffmpeg("-f", "lavfi", "-i", "color=size=8194x2:rate=1:duration=1", "-c:v", "rawvideo",
               str(self.root / "wide.nut"))
        self._rejects(self.root / "wide.nut", "DIMENSION_LIMIT")
        clip = valid_mp4(self.root / "three.mp4", seconds=3)
        self._rejects(clip, "DURATION_LIMIT", MediaProbeLimits(max_duration_seconds=1))
        self._rejects(clip, "FRAME_LIMIT", MediaProbeLimits(max_frames=10))
        args = ["-f", "lavfi", "-i", "sine=duration=1"] + ["-map", "0:a"] * 33
        ffmpeg(*args, "-c:a", "pcm_s16le", str(self.root / "streams.mkv"))
        self._rejects(self.root / "streams.mkv", "STREAM_LIMIT")

    def test_empty_and_special_files_never_reach_a_decoder(self) -> None:
        (self.root / "empty.mp4").write_bytes(b"")
        with self.assertRaises(RuntimeError):
            self._admit(self.root / "empty.mp4")
        link = self.root / "link.mp4"
        link.symlink_to(valid_mp4(self.root / "target.mp4"))
        with self.assertRaises((RuntimeError, OSError)):
            self._admit(link)


if __name__ == "__main__":
    unittest.main()
