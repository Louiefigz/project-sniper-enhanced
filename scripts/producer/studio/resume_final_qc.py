"""Reuse a completed native capture; run unchanged final encoded/audio QC afresh."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from audio.mastering_profile import NATIVE_SHORT_MASTERING_PROFILE
from cut_preview_io import write_new
from studio.native_run import utc
from studio.native_runtime import digest
from studio.native_short_export import prepare
from studio.native_short_pipeline import NativeShortPipeline
from studio.native_short_resume import render_stage_for_attempt
from studio.native_stage_evidence import require
from studio.native_short_capture_resume import (
    CAPTURE_STATUS, NATIVE_STATUS, STUDIO, capture_artifacts, bind_capture_media,
    seal_capture, read_capture,
)

FinalQcPipeline = NativeShortPipeline


def prepare_resume(args: argparse.Namespace) -> tuple[dict, dict]:
    """Delegate the legacy CLI to normal exact attempt and capture recovery admission."""
    capture, _pins = read_capture(args.capture_stage, args.render_stage)
    source = Path(capture['root'])
    require(render_stage_for_attempt(source) == args.render_stage, 'capture uses another render seal')
    options = argparse.Namespace(project=Path(capture['project']), output=args.output,
        verify_from=None, resume_from=source, cache=None, reference_map=None,
        audio_donor=None, picture_donor=None, cached_native_batches=False,
        acquire_source_cache=False, render_only=False,
        audio_profile=NATIVE_SHORT_MASTERING_PROFILE.identity, unused_ram_advisory=False)
    request, environment = prepare(options)
    require(request.get('captureStage') == str(args.capture_stage), 'normal exporter selected another capture')
    request['pins'][str(Path(__file__).resolve())] = digest(Path(__file__).resolve())
    return request, environment


def execute(args: argparse.Namespace) -> bool:
    """Run final QC as a fresh normal owner, with no capture or render subprocess."""
    invocation = (time.monotonic(), utc())
    request, environment = prepare_resume(args)
    write_new(Path(request['output']) / 'export-request.json', request)
    return FinalQcPipeline(request, environment).execute(invocation=invocation)


def main() -> None:
    """Seal first to permit PNG pruning; resume later into a fresh output directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('render_stage', type=Path)
    parser.add_argument('capture_root', type=Path)
    parser.add_argument('output', type=Path, nargs='?')
    parser.add_argument('--seal-only', action='store_true')
    args = parser.parse_args()
    args.render_stage = args.render_stage.absolute()
    args.capture_root = args.capture_root.absolute()
    if args.seal_only:
        require(args.output is None, '--seal-only does not accept an output attempt')
        print(seal_capture(args.capture_root, args.render_stage))
        return
    require(args.output is not None, 'final QC requires a fresh output directory')
    args.capture_stage = args.capture_root / 'capture-stage.json'
    raise SystemExit(0 if execute(args) else 1)


if __name__ == '__main__':
    main()
