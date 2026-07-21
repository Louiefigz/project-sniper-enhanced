"""Adversarial source-discovery, transform, and epoch tests."""
from __future__ import annotations

import json
import os
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _common import pl  # noqa: F401
from headless import container_io
from headless import safe_source_files


def _tree(root: str, html: str) -> Path:
    motion = Path(root) / "templates" / "motion"
    (motion / "compositions").mkdir(parents=True)
    (motion / "vendor" / "gsap").mkdir(parents=True)
    (motion / "compositions" / "card.html").write_text(html)
    (motion / "hyperframes.json").write_text("{}")
    (motion / "index.html").write_text("<html></html>")
    (motion / "package.json").write_text("{}")
    (motion / "tokens.css").write_text("body{}")
    (motion / "vendor" / "gsap" / "gsap.min.js").write_text("gsap")
    return motion


def _snapshot(root: str, stage: str, html: str, spec: dict | None = None,
              duration: float | None = None):
    composition = container_io.CompositionInput(
        "compositions/card.html", html, duration=duration)
    return container_io.create_snapshot(root, composition, spec or {}, stage)


class SourceClosureAdversarialTests(unittest.TestCase):
    def test_spaced_case_varied_attributes_are_captured(self) -> None:
        html = ("<main data-composition-id=\"x\" data-duration=\"1\" "
                "data-composition-variables='[]'>"
                '<LINK HREF = "/tokens.css"><SCRIPT SRC = '
                '"/vendor/gsap/gsap.min.js"></SCRIPT></main>')
        with tempfile.TemporaryDirectory() as root, \
                tempfile.TemporaryDirectory() as stage:
            _tree(root, html)
            sealed = _snapshot(root, stage, html)
            paths = {row["path"] for row in sealed.manifest}
            self.assertIn("motion/tokens.css", paths)
            self.assertIn("motion/vendor/gsap/gsap.min.js", paths)

    def test_relative_base_and_remote_css_dependencies_fail_closed(self) -> None:
        cases = (
            '<script src="tool.js"></script>',
            '<base href="/"><script src="/tool.js"></script>',
            '<style>@import url("https://example.invalid/x.css")</style>',
        )
        for body in cases:
            html = (f"<main data-composition-id=\"x\" data-duration=\"1\" "
                    f"data-composition-variables='[]'>"
                    f'{body}</main>')
            with self.subTest(body=body), tempfile.TemporaryDirectory() as root, \
                    tempfile.TemporaryDirectory() as stage:
                _tree(root, html)
                with self.assertRaises(RuntimeError):
                    _snapshot(root, stage, html)

    def test_local_css_url_is_added_recursively(self) -> None:
        html = ("<main data-composition-id=\"x\" data-duration=\"1\" "
                "data-composition-variables='[]'>"
                '<link href="/tokens.css"></main>')
        with tempfile.TemporaryDirectory() as root, \
                tempfile.TemporaryDirectory() as stage:
            motion = _tree(root, html)
            (motion / "images").mkdir()
            (motion / "images" / "proof.svg").write_text("proof")
            (motion / "tokens.css").write_text(
                'body{background:url("/images/proof.svg")}')
            sealed = _snapshot(root, stage, html)
            self.assertIn("motion/images/proof.svg",
                          {row["path"] for row in sealed.manifest})

    def test_quoted_css_url_with_spaces_is_captured(self) -> None:
        html = ("<main data-composition-id=\"x\" data-duration=\"1\" "
                "data-composition-variables='[]'>"
                '<link href="/tokens.css"></main>')
        with tempfile.TemporaryDirectory() as root, \
                tempfile.TemporaryDirectory() as stage:
            motion = _tree(root, html)
            (motion / "images").mkdir()
            (motion / "images" / "proof card.svg").write_text("proof")
            (motion / "tokens.css").write_text(
                'body{background:url("/images/proof card.svg")}')
            sealed = _snapshot(root, stage, html)
            self.assertIn("motion/images/proof card.svg",
                          {row["path"] for row in sealed.manifest})

    def test_css_image_set_string_dependencies_fail_closed(self) -> None:
        html = ("<main data-composition-id=\"x\" data-duration=\"1\" "
                "data-composition-variables='[]'>"
                '<link href="/tokens.css"></main>')
        for value in ('image-set("/images/a.png" 1x)',
                      '-webkit-image-set("/images/a.png" 1x)'):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as root, \
                    tempfile.TemporaryDirectory() as stage:
                motion = _tree(root, html)
                (motion / "tokens.css").write_text(f"body{{background:{value}}}")
                with self.assertRaisesRegex(RuntimeError, "image-set"):
                    _snapshot(root, stage, html)

    def test_js_modules_and_svg_fragment_dependencies_fail_closed(self) -> None:
        cases = (
            ('<script src="/loader.js"></script>', "loader.js",
             'import "/hidden.js";'),
            ('<script src="/loader.js"></script>', "loader.js",
             'foo(); import x from "/hidden.js";'),
            ('<script src="/loader.js"></script>', "loader.js",
             'import/*comment*/("/hidden.js");'),
            ('<script type=" MODULE " src="/loader.js"></script>',
             "loader.js", "safe();"),
            ('<svg><use xlink:href="/icons.svg#check"></use></svg>', None, None),
        )
        for body, name, contents in cases:
            html = (f"<main data-composition-id=\"x\" data-duration=\"1\" "
                    f"data-composition-variables='[]'>{body}</main>")
            with self.subTest(body=body), tempfile.TemporaryDirectory() as root, \
                    tempfile.TemporaryDirectory() as stage:
                motion = _tree(root, html)
                if name is not None:
                    (motion / name).write_text(contents)
                with self.assertRaises(RuntimeError):
                    _snapshot(root, stage, html)

    def test_intermediate_directory_symlink_swap_is_rejected(self) -> None:
        html = ("<main data-composition-id=\"x\" data-duration=\"1\" "
                "data-composition-variables='[]'>"
                '<script src="/vendor/gsap/gsap.min.js"></script></main>')
        with tempfile.TemporaryDirectory() as root, \
                tempfile.TemporaryDirectory() as outside, \
                tempfile.TemporaryDirectory() as stage:
            motion = _tree(root, html)
            outside_path = Path(outside)
            (outside_path / "gsap").mkdir()
            (outside_path / "gsap" / "gsap.min.js").write_text("OUTSIDE")
            original_open = safe_source_files.os.open
            swapped = False

            def swap(part, flags, *args, **kwargs):
                nonlocal swapped
                if part == "vendor" and kwargs.get("dir_fd") is not None and not swapped:
                    (motion / "vendor").rename(motion / "vendor-safe")
                    (motion / "vendor").symlink_to(outside_path, target_is_directory=True)
                    swapped = True
                return original_open(part, flags, *args, **kwargs)

            with mock.patch.object(safe_source_files.os, "open", side_effect=swap), \
                    self.assertRaises(OSError):
                _snapshot(root, stage, html)

    def test_only_trusted_duration_transform_can_change_source_html(self) -> None:
        html = ("<main data-composition-id=\"x\" data-duration=\"1\" "
                "data-composition-variables='[]'>SAFE</main>")
        with tempfile.TemporaryDirectory() as root, \
                tempfile.TemporaryDirectory() as stage:
            _tree(root, html)
            sealed = _snapshot(root, stage, html, duration=2.5)
            with tarfile.open(sealed.path) as archive:
                rendered = archive.extractfile(
                    "motion/compositions/card.html").read().decode()
            self.assertIn('data-duration="2.5"', rendered)
        with tempfile.TemporaryDirectory() as root, \
                tempfile.TemporaryDirectory() as stage:
            _tree(root, html)
            forged = html.replace("SAFE", "FORGED")
            with self.assertRaisesRegex(RuntimeError, "named source"):
                _snapshot(root, stage, forged, duration=2.5)

    def test_mutating_caller_spec_cannot_create_a_hybrid_epoch(self) -> None:
        html = ("<main data-composition-id=\"x\" data-duration=\"1\" "
                "data-composition-variables='[]'></main>")
        with tempfile.TemporaryDirectory() as root, \
                tempfile.TemporaryDirectory() as stage:
            motion = _tree(root, html)
            (motion / "a.svg").write_text("A")
            caller = {"iconFile": "a.svg"}

            def resolve(entry, _html):
                caller["iconFile"] = "b.svg"
                return [{"field": "iconFile", "selector": entry["spec"]["iconFile"],
                         "path": str(motion / "a.svg")}]

            with mock.patch("headless.container_io.resolved_assets",
                            side_effect=resolve):
                sealed = _snapshot(root, stage, html, caller)
            with tarfile.open(sealed.path) as archive:
                variables = json.load(archive.extractfile("request/variables.json"))
            self.assertEqual(variables, {"iconFile": "a.svg"})
            self.assertEqual(sealed.asset_bindings[0]["selector"], "a.svg")
            self.assertEqual(caller, {"iconFile": "b.svg"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
