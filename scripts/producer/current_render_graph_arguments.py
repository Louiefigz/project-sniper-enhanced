"""Typed current-render command inputs, including an explicit audio capability."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from current_render_graph_inputs import DEFAULT_CACHE, GraphBuildInputs


@dataclass(frozen=True)
class RunConfig:
    """Controller-owned execution arguments for one real renderer phase."""

    phase: str
    inputs: GraphBuildInputs
    next_plan_path: Path
    force_full: bool
    defer_active: bool
    command: tuple[str, ...]


def parse_args(argv: list[str] | None) -> RunConfig:
    """Parse closed graph policy while retaining the exact caller-owned command."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", required=True, choices=("base", "assemble"))
    parser.add_argument("--producer-dir", required=True, type=Path)
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--next-plan", type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--base", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--force-full", action="store_true")
    parser.add_argument("--defer-active", action="store_true")
    parser.add_argument("--audio-clock-policy", choices=("legacy-v1", "source-float-v2"), default="legacy-v1")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = tuple(args.command[1:] if args.command[:1] == ["--"] else args.command)
    producer_dir = args.producer_dir.resolve(strict=True)
    artifact_dir = (args.artifact_dir or producer_dir).resolve(strict=True)
    if not artifact_dir.is_dir():
        parser.error("--artifact-dir must be a directory")
    if args.defer_active and args.phase != "assemble":
        parser.error("--defer-active is valid only for assemble")
    inputs = GraphBuildInputs(producer_dir, args.plan.resolve(strict=True),
        args.manifest.resolve(strict=True), args.base.absolute(), args.output.absolute(),
        args.cache_dir.absolute(), "forced-full" if args.force_full else "incremental",
        artifact_dir, args.audio_clock_policy)
    return RunConfig(args.phase, inputs, (args.next_plan or args.plan).absolute(),
                     args.force_full, args.defer_active, command)
