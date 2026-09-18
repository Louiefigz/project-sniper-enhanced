"""Resolve Studio review inputs once and preserve them across CLI handoffs."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from studio.studio_server import StudioServerError

_PKG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@dataclass(frozen=True)
class ProducerPaths:
    """The producer-directory files the review lane touches."""

    root: str

    @classmethod
    def resolve(cls, producer_dir: str) -> "ProducerPaths":
        """Validate and absolutize the producer directory."""
        root = os.path.abspath(producer_dir)
        if not os.path.isdir(root):
            raise StudioServerError(f"not a directory: {root}")
        return cls(root)

    @property
    def plan(self) -> str:
        """Return the canonical plan path."""
        return os.path.join(self.root, "edit_plan.json")

    @property
    def base(self) -> str:
        """Return the graphics-free picture path."""
        return os.path.join(self.root, "base_final.mp4")

    @property
    def studio_dir(self) -> str:
        """Return the generated review-only project directory."""
        return os.path.join(self.root, "studio")

    @property
    def manifest(self) -> str:
        """Return the beside-plan manifest location, when present."""
        return os.path.join(self.root, "asset_manifest.json")

    @property
    def fingerprint(self) -> str:
        """Return the base dependency fingerprint path."""
        return os.path.join(self.root, "base.fingerprint.json")

    @property
    def final(self) -> str:
        """Return the canonical output path, not an approval claim."""
        return os.path.join(self.root, "final.mp4")


def find_asset_manifest(root: str) -> str | None:
    """Search the established beside-plan then parent/source layouts."""
    beside = os.path.join(root, "asset_manifest.json")
    if os.path.isfile(beside):
        return beside
    node = root
    for _ in range(3):
        parent = os.path.dirname(node)
        if not parent or parent == node:
            break
        node = parent
        candidate = os.path.join(node, "source", "asset_manifest.json")
        if os.path.isfile(candidate):
            return candidate
    return None


def resolve_manifest(paths: ProducerPaths, override: str | None = None) -> str | None:
    """Resolve explicit intent without falling back from an invalid override."""
    if override is None:
        return find_asset_manifest(paths.root)
    absolute = os.path.abspath(override)
    if not override or not os.path.isfile(absolute):
        raise StudioServerError(f"asset manifest is not a file: {absolute}")
    return absolute


def assemble_args(paths: ProducerPaths, manifest: str | None = None) -> list[str]:
    """Build argv using the same manifest resolved for the sync gates."""
    args = [sys.executable, os.path.join(_PKG_ROOT, "assemble.py"),
            paths.base, paths.plan, paths.final,
            "--auto-base", "--fingerprint", paths.fingerprint]
    resolved = resolve_manifest(paths, manifest)
    if resolved:
        args += ["--manifest", resolved]
    return args
