"""Project-library dedup and deterministic source naming."""
import unittest
from unittest.mock import patch

from _common import *  # noqa: F401,F403
from ingest_probe import MediaProbe
from palmier.media import MediaLibrary


def _probe(duration=5.0, width=1920, height=1080):
    return MediaProbe(duration, 24.0, False, width, height, 0,
                      True, 2, 48000)


class MediaClient:
    def __init__(self, assets):
        self.assets = assets
        self.calls = []

    def call_json(self, tool, arguments=None):
        self.calls.append((tool, arguments or {}))
        if tool == "get_media":
            return {"assets": self.assets}
        if tool == "import_media":
            return {"mediaRef": "new-ref"}
        raise AssertionError(tool)

    def wait_media(self, media_ref):
        return {"id": media_ref, "name": "raw-file", "durationSeconds": 5.0,
                "width": 1920, "height": 1080}

    def call(self, tool, arguments=None):
        self.calls.append((tool, arguments or {}))
        return "ok"


class MediaLibraryTests(unittest.TestCase):
    @patch("palmier.media.probe_media", return_value=_probe())
    def test_adopts_exact_library_match_without_import(self, _mock_probe):
        assets = [
            {"id": "z", "name": "graphic", "durationSeconds": 5.0,
             "width": 1920, "height": 1080},
            {"id": "a", "name": "graphic", "durationSeconds": 5.0,
             "width": 1920, "height": 1080},
        ]
        client = MediaClient(assets)
        result = MediaLibrary(client, "abc123", lambda _phase: None).ensure(
            {"gfx:0": "/cache/graphic.mov"}, {})
        self.assertEqual(result.refs["gfx:0"], "a")
        self.assertNotIn("import_media", [tool for tool, _args in client.calls])

    @patch("palmier.media.probe_media", return_value=_probe())
    def test_dimension_mismatch_imports_and_assigns_stable_source_name(self, _mock_probe):
        client = MediaClient([{"id": "old", "name": "raw-file",
                               "durationSeconds": 5.0,
                               "width": 3840, "height": 2160}])
        result = MediaLibrary(client, "abcdef1234567890", lambda _phase: None).ensure(
            {"src": "/source/raw-file.mp4"}, {})
        self.assertEqual(result.refs["src"], "new-ref")
        rename = next(args for tool, args in client.calls if tool == "organize_media")
        self.assertEqual(rename["renames"][0]["name"], "sniper-src-abcdef123456")

    def test_live_sidecar_ref_wins_without_probe(self):
        client = MediaClient([{"id": "known", "name": "anything",
                               "durationSeconds": 7.0}])
        with patch("palmier.media.probe_media") as probe:
            result = MediaLibrary(client, "abc", lambda _phase: None).ensure(
                {"music": "/bed.mp3"},
                {"music:/bed.mp3": {"ref": "known", "seconds": 7.0}})
        self.assertEqual(result.refs["music"], "known")
        probe.assert_not_called()


if __name__ == "__main__":
    unittest.main()
