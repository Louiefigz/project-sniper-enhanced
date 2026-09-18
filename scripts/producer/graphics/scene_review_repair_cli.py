#!/usr/bin/env python3
"""Render one changed scene unit into a private dirty-window review clip."""
from __future__ import annotations

import argparse
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from graphics.scene_contract import SceneContractError, canonical_json  # noqa: E402
from graphics.scene_package_contract import (  # noqa: E402
    load_scene_package,
    read_regular_json,
)
from graphics.scene_review_repair import (  # noqa: E402
    SceneReviewRepairRequest,
    repair_scene_review,
)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise SceneContractError(
            f"invalid scene review repair command: {message}")


def _parse(argv: list[str] | None) -> argparse.Namespace:
    parser = _Parser(description=__doc__)
    parser.add_argument("previous_package")
    parser.add_argument("current_package")
    parser.add_argument("--previous-project-authority", required=True)
    parser.add_argument("--current-project-authority", required=True)
    parser.add_argument("--operation-receipt", required=True)
    parser.add_argument("--previous-render-receipt", required=True)
    parser.add_argument("--base-channel-receipt", required=True)
    parser.add_argument("--bundle-store", required=True)
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--review-out", required=True)
    parser.add_argument("--receipt-out", required=True)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--sample-rate", type=int, default=48_000)
    return parser.parse_args(argv)


def _unused_output(path: object, label: str) -> tuple[str, str]:
    if not isinstance(path, str) or not os.path.isabs(path) \
            or os.path.normpath(path) != path:
        raise SceneContractError(f"{label} must be absolute and normalized")
    parent = os.path.dirname(path)
    if os.path.realpath(parent) != parent or os.path.islink(parent) \
            or not os.path.isdir(parent) or os.path.lexists(path):
        raise SceneContractError(
            f"{label} needs a canonical directory and unused filename")
    return path, parent


def _write(path: str, value: dict) -> None:
    target, parent = _unused_output(path, "scene review receipt output")
    descriptor, staged = tempfile.mkstemp(
        prefix=".scene-review-receipt-", dir=parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(canonical_json(value) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.link(staged, target, follow_symlinks=False)
        directory = os.open(
            parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if os.path.lexists(staged):
            os.unlink(staged)


def run(argv: list[str] | None = None) -> dict:
    """Resolve exact package authorities and emit one private-review receipt."""
    args = _parse(argv)
    review_out, _parent = _unused_output(
        args.review_out, "scene review media output")
    previous = load_scene_package(
        os.path.abspath(args.previous_package), args.bundle_store)
    current = load_scene_package(
        os.path.abspath(args.current_package), args.bundle_store)
    result = repair_scene_review(SceneReviewRepairRequest(
        previous=previous,
        current=current,
        previous_project=read_regular_json(
            os.path.abspath(args.previous_project_authority),
            "previous project authority"),
        current_project=read_regular_json(
            os.path.abspath(args.current_project_authority),
            "current project authority"),
        operation_receipt=read_regular_json(
            os.path.abspath(args.operation_receipt),
            "scene treatment operation receipt"),
        previous_render_receipt=read_regular_json(
            os.path.abspath(args.previous_render_receipt),
            "previous scene render receipt"),
        base_channel_receipt=read_regular_json(
            os.path.abspath(args.base_channel_receipt),
            "base channel-normalization receipt"),
        cache_dir=os.path.abspath(args.cache_dir),
        base_path=os.path.abspath(args.base),
        output_path=review_out,
        workers=args.workers,
        sample_rate=args.sample_rate,
    ))
    _write(os.path.abspath(args.receipt_out), result)
    return result


def main(argv: list[str] | None = None) -> int:
    """Emit a single canonical success or failure document."""
    try:
        result, code = run(argv), 0
    except (OSError, ValueError, RuntimeError) as exc:
        result = {
            "schemaVersion": 1, "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
        code = 65
    sys.stdout.write(canonical_json(result).decode("utf-8") + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
