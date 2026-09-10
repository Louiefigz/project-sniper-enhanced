#!/usr/bin/env python3
"""Validate, durably admit, or render one exact ScenePackageV1 reference."""
from __future__ import annotations

import argparse
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from graphics.scene_contract import SceneContractError, canonical_json  # noqa: E402
from graphics.scene_authoring_stage import stage_scene_authoring  # noqa: E402
from graphics.scene_package_contract import (  # noqa: E402
    load_scene_package,
    read_regular_json,
)
from graphics.scene_package_render import (  # noqa: E402
    ScenePackageRenderRequest,
    admit_scene_package,
    render_scene_package,
)
from graphics.scene_text_proposal import (  # noqa: E402
    add_text_proposal_arguments, propose_text,
)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise SceneContractError(f"invalid scene package command: {message}")


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("package_path")
    parser.add_argument("--bundle-store")
    parser.add_argument("--media-snapshot-store")


def _parse(argv: list[str] | None) -> argparse.Namespace:
    """Parse existing package operations or the non-persisting text proposal."""
    parser = _Parser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    add_text_proposal_arguments(commands.add_parser(
        "propose-text", help="SDK text proposal only; never apply, approve or render"))
    stage = commands.add_parser("stage-authoring")
    stage.add_argument("packet_path")
    stage.add_argument("--attempt-dir", required=True)
    validate = commands.add_parser("validate")
    _common(validate)
    package = commands.add_parser("package")
    _common(package)
    package.add_argument("--receipt-out", required=True)
    render = commands.add_parser("render")
    _common(render)
    render.add_argument("--cache-dir", required=True)
    render.add_argument("--workers", type=int, default=2)
    render.add_argument("--receipt-out", required=True)
    return parser.parse_args(argv)


def _output_path(path: object) -> tuple[str, str]:
    if not isinstance(path, str) or not os.path.isabs(path) \
            or os.path.normpath(path) != path:
        raise SceneContractError("receipt output must be absolute and normalized")
    parent = os.path.dirname(path)
    if os.path.realpath(parent) != parent or os.path.islink(parent) \
            or not os.path.isdir(parent) or os.path.lexists(path):
        raise SceneContractError(
            "receipt output needs a canonical directory and unused filename")
    return path, parent


def _write_receipt(path: str, value: dict) -> None:
    target, parent = _output_path(path)
    fd, staged = tempfile.mkstemp(prefix=".scene-receipt-", dir=parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(canonical_json(value) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.link(staged, target, follow_symlinks=False)
        directory_fd = os.open(
            parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if fd >= 0:
            os.close(fd)
        if os.path.lexists(staged):
            os.unlink(staged)


def _read_packet(path: object) -> dict:
    return read_regular_json(path, "authoring packet")


def run(argv: list[str] | None = None) -> dict:
    """Execute one command and return the exact emitted receipt."""
    args = _parse(argv)
    if args.command == "propose-text":
        return propose_text(args)
    if args.command == "stage-authoring":
        return stage_scene_authoring(
            _read_packet(args.packet_path), args.attempt_dir)
    resolved = load_scene_package(args.package_path, args.bundle_store)
    if args.command == "validate":
        return admit_scene_package(resolved, args.media_snapshot_store)
    if args.command == "package":
        result = admit_scene_package(resolved, args.media_snapshot_store)
    else:
        result = render_scene_package(ScenePackageRenderRequest(
            resolved, args.cache_dir, args.media_snapshot_store, args.workers))
    _write_receipt(args.receipt_out, result)
    return result


def main(argv: list[str] | None = None) -> int:
    """Emit exactly one canonical JSON verdict."""
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
    sys.exit(main())
