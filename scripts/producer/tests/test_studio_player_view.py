"""Studio PLAYER acceptance gate — the review project in the real player.

The generator suites prove the emitted files; nothing before this suite ever
looked at the PLAYING timeline, which is how a broken host page (inlined
``</script`` truncation, unscaled 4K slots) shipped. This gate generates a
review project, serves it with the REAL pinned Studio server, drives the
actual player in headless Chrome via ``studio_player_probe.cjs``, seeks
plan-derived beats, and asserts on what renders: zero page errors, zero
console errors / HTTP>=400s, gsap + every timeline registered, each active
slot's mounted comp covering the stage, no raw text outside mounted comps,
and a painted (non-black) base video. Screenshots land in
``tests/.artifacts/studio-player-view/`` for human review.
"""
import glob
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import unittest
import urllib.request

from _common import *  # noqa: F401,F403
from _common import _HAVE_FFMPEG

from graphics.graphics_render import HYPERFRAMES_BIN
from studio.studio_project import GenerateRequest, generate_project
from studio.managed_preview import open_preview, stop_preview
from studio.native_runtime import install_runtime
from studio.studio_server import pick_free_port

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_TESTS_DIR)))
_PROBE = os.path.join(_TESTS_DIR, "studio_player_probe.cjs")
_PUPPETEER_DIR = os.path.join(_REPO_ROOT, "templates", "motion",
                              "node_modules", "puppeteer-core")
_SETTLE_MS = 1200
_COVERAGE_FLOOR = 0.9
_MIN_VIDEO_CHANNEL = 32
_ASPECT_TOLERANCE = 0.002


def _chrome_path() -> str | None:
    """Headless chrome: explicit env override, else puppeteer's cache."""
    env = os.environ.get("PUPPETEER_EXECUTABLE_PATH")
    if env and os.path.isfile(env):
        return env
    hits = glob.glob(os.path.expanduser(
        "~/.cache/puppeteer/chrome-headless-shell/*/chrome-headless-shell-*/"
        "chrome-headless-shell"))
    return sorted(hits)[-1] if hits else None


def _skip_reason() -> str | None:
    if not _HAVE_FFMPEG:
        return "ffmpeg not on PATH"
    if shutil.which("node") is None:
        return "node not on PATH"
    if not os.path.isfile(HYPERFRAMES_BIN):
        return f"pinned hyperframes CLI missing: {HYPERFRAMES_BIN} " \
               "(run npm install in templates/motion)"
    if not os.path.isdir(_PUPPETEER_DIR):
        return f"puppeteer-core missing: {_PUPPETEER_DIR} " \
               "(run npm install in templates/motion)"
    if _chrome_path() is None:
        return "chrome-headless-shell absent — install it with " \
               "`npx puppeteer browsers install chrome-headless-shell` " \
               "or set PUPPETEER_EXECUTABLE_PATH"
    return None


def _player_plan() -> dict:
    """3 real catalog entries at separated windows over a 12s base (like _studio_plan)."""
    return {
        "planVersion": 1,
        "target": {"mode": "short"},
        "cutTrack": [
            {"sourceId": "raw-1", "start": 0.0, "end": 12.0, "speed": 1.0},
        ],
        "graphicsTrack": [
            {"kind": "line-swap", "outStart": 1.0, "outEnd": 3.5,
             "anchor": "own-screen", "reason": "thesis takeover",
             "spec": {"lineA": "More tactics", "lineB": "One system",
                      "swapAt": 1.2, "underlineWord": ""}},
            {"kind": "marker-highlight", "outStart": 4.5, "outEnd": 6.5,
             "anchor": "free-band", "reason": "callout",
             "spec": {"text": "Callout copy", "emphasisWord": "copy",
                      "drawAt": 1, "style": "highlight"}},
            {"kind": "marker-highlight", "outStart": 7.5, "outEnd": 10.5,
             "anchor": "own-screen", "reason": "quote",
             "spec": {"text": "More tactics was never the answer",
                      "emphasisWord": "never", "drawAt": 1}},
        ],
    }


def _make_base_4k(path: str) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", "color=c=0x336699:s=2160x3840:d=12:r=30",
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30",
         "-pix_fmt", "yuv420p", path], check=True)


# The one outside file Studio loads, disclosed in manual/privacy.html.
_DISCLOSED = frozenset({"https://cdn.jsdelivr.net/npm/gsap@3.12.5/dist/MotionPathPlugin.min.js"})


@unittest.skipIf(_skip_reason() is not None, _skip_reason() or "")
class StudioPlayerViewTests(unittest.TestCase):
    """One server + one probe run; every assertion reads the same facts."""

    maxDiff = None

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.mkdtemp(prefix="studio-player-view-")
        cls.addClassCleanup(shutil.rmtree, cls.tmp)
        cls.shots_dir = tempfile.mkdtemp(prefix="studio-player-shots-")
        print(f"Retained synthetic Studio player screenshots: {cls.shots_dir}", flush=True)
        cls.studio_dir = os.path.join(cls.tmp, "studio-gate")
        base = os.path.join(cls.tmp, "base.mp4")
        plan_path = os.path.join(cls.tmp, "edit_plan.json")
        _make_base_4k(base)
        with open(plan_path, "w", encoding="utf-8") as handle:
            json.dump(_player_plan(), handle)
        generate_project(GenerateRequest(plan_path, base, cls.studio_dir))
        with open(os.path.join(cls.studio_dir, "studio.manifest.json"),
                  encoding="utf-8") as handle:
            cls.manifest = json.load(handle)
        cls._start_server()
        cls.result = cls._run_probe()

    INTERACT = False

    @classmethod
    def _start_server(cls) -> None:
        """The stock HyperFrames preview (the player gate's historical baseline)."""
        # Keep tests out of the operator's default 3990-3999 preview range.
        cls.port = pick_free_port((41000, 41100))
        # --foreground: without a terminal the stock CLI otherwise re-launches itself detached in
        # a new session and exits, so the server escaped this cleanup. Its session files go to
        # this test's folder, not the operator's ~/.local/state.
        cls.server = subprocess.Popen(
            ["node", HYPERFRAMES_BIN, "preview", cls.studio_dir,
             "--port", str(cls.port), "--foreground", "--no-open"],
            cwd=cls.studio_dir, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env={**os.environ, "XDG_STATE_HOME": os.path.join(cls.tmp, "state")},
            start_new_session=True)
        cls.addClassCleanup(cls._stop_server)
        cls._wait_ready()

    @classmethod
    def _stop_server(cls) -> None:
        """Reap this test's own server even when setUpClass fails."""
        if cls.server.poll() is not None:
            return
        try:
            os.killpg(cls.server.pid, signal.SIGTERM)
            cls.server.wait(timeout=10)
        except ProcessLookupError:
            cls.server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(cls.server.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            cls.server.wait(timeout=5)

    @classmethod
    def _server_exited(cls) -> bool:
        return cls.server.poll() is not None

    @classmethod
    def _wait_ready(cls) -> None:
        for _ in range(60):
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{cls.port}/api/projects",
                        timeout=2) as response:
                    if response.status == 200:
                        return
            except OSError:
                pass
            if cls._server_exited():
                raise RuntimeError("studio preview server exited early")
            import time
            time.sleep(0.5)
        raise RuntimeError("studio preview server never became ready")

    @classmethod
    def _run_probe(cls) -> dict:
        beats = [round((e["outStart"] + e["outEnd"]) / 2.0, 2)
                 for e in cls.manifest["entries"]]
        config = {
            "puppeteerDir": _PUPPETEER_DIR,
            "chrome": _chrome_path(),
            "url": f"http://127.0.0.1:{cls.port}/#project/"
                   f"{os.path.basename(cls.studio_dir)}",
            "shotsDir": cls.shots_dir,
            "settleMs": _SETTLE_MS,
            "beats": beats,
            "interact": cls.INTERACT,
            "allowExternal": sorted(_DISCLOSED),  # everything else is answered inside the probe
        }
        config_path = os.path.join(cls.tmp, "probe-config.json")
        with open(config_path, "w", encoding="utf-8") as handle:
            json.dump(config, handle)
        proc = subprocess.run(["node", _PROBE, config_path],
                              capture_output=True, text=True, timeout=120)
        if proc.returncode != 0:
            raise RuntimeError(
                f"probe failed ({proc.returncode}): {proc.stderr[-800:]}")
        return json.loads(proc.stdout)

    # ---- the gate ----------------------------------------------------

    def _expected_slots(self, beat: float) -> list[dict]:
        return [entry for entry in self.manifest["entries"]
                if entry["outStart"] < beat < entry["outEnd"]]

    def test_host_frame_and_player_found(self) -> None:
        self.assertTrue(self.result["hostFrameFound"],
                        "player never exposed the review host frame "
                        f"(shots: {self.shots_dir})")
        self.assertEqual(len(self.result["beats"]),
                         len(self.manifest["entries"]))

    def test_server_stays_attached_for_cleanup(self) -> None:
        # Without --foreground the stock CLI re-launches itself detached and exits; the
        # class cleanup could then never stop the server it started.
        self.assertFalse(self._server_exited(), "the preview server detached or exited")

    def test_stock_page_attempts_analytics(self) -> None:
        # Negative control for StudioBuyerRoutePrivacyTests: the published page tries to send
        # analytics (the probe answers those requests locally, so none leaves this Mac), so the
        # same probe on the adapted runtime could observe a leak.
        self.assertTrue([url for url in self.result["externalRequests"] if "posthog" in url],
                        "the stock Studio page sent no analytics; re-check the privacy gate's premise")

    def test_no_page_errors(self) -> None:
        self.assertEqual(self.result["pageErrors"], [])

    def test_no_console_errors_or_failed_requests(self) -> None:
        self.assertEqual(self.result["consoleErrors"], [])
        self.assertEqual(self.result["badResponses"], [])

    def test_gsap_and_every_timeline_registered(self) -> None:
        for facts in self.result["beats"]:
            self.assertIn(facts["gsapType"], ("function", "object"),
                          "gsap must be live in the host frame")
            keys = set(facts["timelineKeys"])
            self.assertNotEqual(keys - {"__proxied"}, set(),
                                "only the Studio proxy marker is registered "
                                "— the page registered zero timelines")
            self.assertIn("review", keys)
            for entry in self.manifest["entries"]:
                self.assertIn(entry["instanceId"], keys)

    def test_active_slots_visible_and_stage_covering(self) -> None:
        for facts in self.result["beats"]:
            slots = {slot["id"]: slot for slot in facts["slots"]}
            stage_w, stage_h = facts["stage"]
            for entry in self._expected_slots(facts["beat"]):
                slot = slots.get(entry["slot"])
                self.assertIsNotNone(
                    slot, f"slot {entry['slot']} missing at {facts['beat']}s")
                self.assertTrue(
                    slot["visible"],
                    f"{entry['slot']} not visible at {facts['beat']}s")
                self.assertIsNotNone(
                    slot["childRect"],
                    f"{entry['slot']} mounted nothing at {facts['beat']}s")
                comp_html = os.path.join(self.studio_dir, entry["file"])
                self.assertTrue(os.path.isfile(comp_html))
                same_aspect = self._same_aspect(slot, (stage_w, stage_h))
                if entry["anchor"] == "own-screen" or same_aspect:
                    self.assertGreaterEqual(
                        slot["coverage"], _COVERAGE_FLOOR,
                        f"{entry['slot']} ({entry['kind']}) covers "
                        f"{slot['coverage']:.2f} of the stage at "
                        f"{facts['beat']}s — unscaled mount? "
                        f"(shots: {self.shots_dir})")
                else:
                    x, y, w, h = slot["childRect"]
                    self.assertGreater(w * h, 0)
                    self.assertGreaterEqual(x, -2)
                    self.assertGreaterEqual(y, -2)
                    self.assertLessEqual(x + w, stage_w + 2)
                    self.assertLessEqual(y + h, stage_h + 2)

    @staticmethod
    def _same_aspect(slot: dict, stage: tuple[float, float]) -> bool:
        _, _, width, height = slot["childRect"]
        if not width or not height or not stage[1]:
            return False
        return abs(width / height
                   - stage[0] / stage[1]) <= _ASPECT_TOLERANCE * 4

    def test_no_raw_text_outside_comps(self) -> None:
        for facts in self.result["beats"]:
            self.assertEqual(
                facts["rawText"], [],
                f"raw text in the player DOM at {facts['beat']}s "
                f"(shots: {self.shots_dir})")

    def test_video_painted(self) -> None:
        for facts in self.result["beats"]:
            video = facts["video"]
            self.assertIsNotNone(video, "review-base video element missing")
            self.assertGreaterEqual(video["readyState"], 2,
                                    f"video not decodable at {facts['beat']}s")
            self.assertIsNotNone(video["maxChannel"],
                                 video.get("sampleError"))
            self.assertGreater(video["maxChannel"], _MIN_VIDEO_CHANNEL,
                               f"black frame at {facts['beat']}s")

    def test_timeline_plays(self) -> None:
        play = self.result["play"]
        self.assertIsNotNone(play)
        self.assertGreater(play["after"], play["before"],
                           "player.play() did not advance the timeline")



_ANALYTICS_KEY = re.compile(r"phc_[A-Za-z0-9]{20,}")
_SCRIPT_SRC = re.compile(r'<script[^>]+src="(/[^"]+\.js)"')

class StudioBuyerRoutePrivacyTests(StudioPlayerViewTests):
    """The player gate through the buyer's route, plus Studio's privacy gate.

    Studio opens the way install/studio.command opens it (managed_preview on the
    adapted runtime), in a fresh browser profile with no stored opt-out. The page
    is driven through playback, seeking and editing input, then left so Studio
    flushes any queued analytics. No analytics request may be attempted, and only
    the disclosed download may leave the Mac.
    """

    INTERACT = True
    test_stock_page_attempts_analytics = None  # the control belongs to the stock route only

    @classmethod
    def _start_server(cls) -> None:
        cls.cli = str(install_runtime() / "dist" / "cli.js")
        record = open_preview(cls.studio_dir, pick_free_port((41100, 41200)))
        cls.addClassCleanup(stop_preview, cls.studio_dir)
        cls.port, cls.pid = record.port, record.pid
        cls.server_command = subprocess.run(["/bin/ps", "-o", "command=", "-p", str(record.pid)],
                                            capture_output=True, text=True, check=False).stdout
        cls._wait_ready()

    @classmethod
    def _server_exited(cls) -> bool:
        try:
            os.kill(cls.pid, 0)
        except ProcessLookupError:
            return True
        return False

    def _served(self, path: str) -> str:
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=10) as response:
            return response.read().decode("utf-8", "replace")

    def test_served_by_the_adapted_runtime(self) -> None:
        self.assertIn(f"{self.cli} preview", self.server_command)

    def test_served_studio_page_has_no_analytics_key(self) -> None:
        scripts = _SCRIPT_SRC.findall(self._served("/"))
        self.assertTrue(scripts, "the Studio page names its bundle")
        for script in scripts:
            self.assertIsNone(_ANALYTICS_KEY.search(self._served(script)), f"{script} carries an analytics key")

    def test_fresh_profile_has_no_opt_out(self) -> None:
        # The absence of analytics must come from Sniper's runtime, not from a browser setting.
        self.assertIsNone(self.result["optOut"]["stored"])
        self.assertNotEqual(self.result["optOut"]["doNotTrack"], "1")

    def test_no_analytics_request_is_attempted(self) -> None:
        self.assertEqual([url for url in self.result["externalRequests"] if "posthog" in url], [])

    def test_only_the_disclosed_download_leaves_the_mac(self) -> None:
        self.assertLessEqual(set(self.result["externalRequests"]), _DISCLOSED)


if __name__ == "__main__":
    unittest.main()
