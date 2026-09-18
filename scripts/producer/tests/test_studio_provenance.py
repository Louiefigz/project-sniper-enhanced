"""Installed Studio selections must save timing in the owning host file."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from test_studio_host_ids import _CLI, _fixture
from studio.project_writer import build_index_html

_PROBE = Path(__file__).with_name("_studio_provenance_probe.mjs")


@unittest.skipUnless(shutil.which("node") and _CLI.is_file(), "installed CLI and Node required")
class StudioProvenanceTests(unittest.TestCase):
    """Execute the installed resolver, never the CLI/bootstrap or a copied imitation."""

    def _probe(self, mode: str = "valid", fault: str = "", cli_path: Path | None = None) -> dict:
        """Use actual SDK DOM parsing and exact original generated host provenance."""
        base, clips = _fixture()
        result = subprocess.run(
            ["node", str(_PROBE), str(cli_path or _CLI), str(_CLI.parents[5])],
            input=json.dumps({"mode": mode, "fault": fault,
                             "html": build_index_html(base, clips, "Review", False)}),
            text=True, capture_output=True, timeout=5, check=True)
        return json.loads(result.stdout)

    def test_exact_pinned_resolver_retains_children_and_corrects_host(self) -> None:
        """Preserve every original host/descendant/timing assertion against current bytes."""
        row = self._probe()
        self.assertEqual(row["initial"], "compositions/one.html")
        self.assertEqual(row["host"], "index.html")
        self.assertEqual(row["compositionSrc"], "index.html")
        self.assertEqual(row["inner"], "compositions/one.html")
        self.assertEqual(row["late"], "compositions/one.html")
        self.assertEqual(row["nested"], "compositions/nested.html")
        self.assertEqual(row["timing"], ["1", "2"])
        self.assertEqual(row["errors"], [])

    def test_unexpected_host_identity_or_source_reports_without_rewriting(self) -> None:
        """Original identity/path negatives remain refusals, with no automatic repair."""
        for mode, expected in [("bad-id", "compositions/one.html"),
                               ("bad-file", "compositions/unknown.html")]:
            with self.subTest(mode=mode):
                row = self._probe(mode)
                self.assertEqual(row["host"], expected)
                self.assertEqual(len(row["errors"]), 1)
                self.assertIn("source attribution blocked: gfx-01", row["errors"][0])

    def test_actual_composition_map_fallback_is_not_replaced_by_a_stub(self) -> None:
        """Exercise the installed initializer, setter and fallback helper together."""
        self.assertEqual(self._probe()["mapped"], "compositions/mapped.html")

    def test_installed_package_alias_resolves_to_the_same_original_cli(self) -> None:
        """Private test mirrors may symlink installed packages without copying or changing them."""
        with tempfile.TemporaryDirectory(prefix="sniper-provenance-alias-", dir="/private/tmp") as directory:
            alias = Path(directory) / "TEST-cli-alias.js"
            alias.symlink_to(_CLI)
            self.assertEqual(self._probe(cli_path=alias)["host"], "index.html")

    def test_missing_or_ambiguous_installed_resolver_dependencies_refuse(self) -> None:
        """Fault only in-memory copies and require refusal before provenance executes."""
        for fault in ("missing-resolver", "ambiguous-resolver", "missing-helper", "missing-map",
                      "missing-map-setter", "unexpected-dependency"):
            with self.assertRaises(subprocess.CalledProcessError) as result:
                self._probe(fault=fault)
            self.assertIn("Missing or ambiguous", result.exception.stderr)


if __name__ == "__main__":
    unittest.main()
