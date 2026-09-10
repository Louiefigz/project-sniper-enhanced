"""Stage the shared motion runtime, icon closure and base video for Studio.

Mirrors the asset-resolution parity contract of
``src/app/api/producer/comp-html/route.ts``: tokens.css and the pinned local
GSAP/motion-tokens files are made resolvable under the Studio server (loaded
once from the host page's head), and every icon an entry's spec resolves is
copied under ``assets/icons/`` so the comps' ``"/icons/…"`` references — after
``comp_transform.rewrite_icon_refs`` — resolve relative to the project.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass

from graphics.graphics_render import (
    GSAP_CORE,
    MOTION_DIR,
    MOTION_TOKENS_JS,
    TOKENS_CSS,
)
from studio import StudioProjectError

SPLIT_TEXT_JS = os.path.join(MOTION_DIR, "vendor", "gsap", "SplitText.min.js")

_SHARED = (
    (TOKENS_CSS, os.path.join("assets", "tokens.css")),
    (GSAP_CORE, os.path.join("assets", "vendor", "gsap.min.js")),
    (MOTION_TOKENS_JS, os.path.join("assets", "vendor", "motion-tokens.js")),
    (SPLIT_TEXT_JS, os.path.join("assets", "vendor", "SplitText.min.js")),
)


@dataclass(frozen=True)
class BaseVideoStage:
    """How the base footage landed in the project."""

    rel_path: str
    bytes: int


def _sanitized_js(text: str) -> str:
    """Neutralize literal ``</script`` sequences for single-file inlining.

    Studio's preview server bundles the whole project into one HTML page
    (``bundleToSingleHtml``) and inlines every staged head script into a
    single ``<script>`` element without escaping. The HTML parser ends that
    element at the FIRST ``</script`` it sees — motion-tokens.js carries one
    inside its usage comment, which truncated the merged script (SyntaxError,
    ``gsap`` undefined, zero timelines), dumped the file's tail into the DOM
    as page text, and turned the comment's example tag into a 404ing script.
    ``<\\/script`` is byte-equivalent JS in comments, strings and regexes.
    """
    return text.replace("</script", "<\\/script")


def _place(source: str, dest: str) -> None:
    """Copy one file into the project, replacing any previous stage.

    ``.js`` assets are staged through :func:`_sanitized_js` so the preview
    bundler can safely inline them into the host page.
    """
    if not os.path.isfile(source):
        raise StudioProjectError(f"shared asset missing: {source}")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.lexists(dest):
        os.remove(dest)
    if dest.endswith(".js"):
        with open(source, encoding="utf-8") as handle:
            text = handle.read()
        with open(dest, "w", encoding="utf-8") as handle:
            handle.write(_sanitized_js(text))
        return
    shutil.copyfile(source, dest)


def stage_shared_assets(out_dir: str) -> list[str]:
    """Copy tokens.css + pinned gsap/SplitText/motion-tokens into assets/."""
    staged = []
    for source, rel in _SHARED:
        _place(source, os.path.join(out_dir, rel))
        staged.append(rel)
    return staged


def stage_icons(out_dir: str, icon_rows: list[dict]) -> list[str]:
    """Copy each resolved icon (``template_contract.resolved_assets`` rows)
    to the destination the comps' rewritten runtime concat will request."""
    staged = []
    for row in icon_rows:
        selector = str(row["selector"])
        name = selector if "." in os.path.basename(selector) \
            else selector + ".svg"
        rel = os.path.join("assets", "icons", name)
        _place(str(row["path"]), os.path.join(out_dir, rel))
        staged.append(rel)
    return sorted(set(staged))


def stage_base_video(out_dir: str, base_video: str) -> BaseVideoStage:
    """Copy the base footage into assets/.

    Always a real copy: Studio's preview file server refuses symlinks
    (verified live 2026-08-27 — a symlinked assets/base.mp4 404s while the
    identical copied file serves 200).
    """
    source = os.path.abspath(base_video)
    if not os.path.isfile(source):
        raise StudioProjectError(f"base video not found: {base_video}")
    ext = os.path.splitext(source)[1] or ".mp4"
    rel = os.path.join("assets", f"base{ext}")
    dest = os.path.join(out_dir, rel)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.lexists(dest):
        os.remove(dest)
    shutil.copyfile(source, dest)
    return BaseVideoStage(rel_path=rel, bytes=os.path.getsize(dest))
