"""Explicit TEST-only A/B on identical retained page bytes; never runs on import.

DRAFT: do not execute until the root grants a source-stable media window. This
does not create media. Inputs must be already-rendered PNG/RGBA caption pages,
not C0679 or any candidate. All comparator failures and actual timing are kept.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from unittest.mock import patch

import captions.caption_page_decode as decoder
import captions.caption_page_proof as proof_parser
import audit.audit_glitch_scan as progress_parser
import headless.process_runner as process_runner
import palmier.process_deadline as process_deadline
from palmier.process_deadline import use_process_deadline
from _caption_page_ab_support import PageCommandRecorder, TestPageDeadline, expected_json, file_observation, write_json
from _caption_page_legacy_proof import LegacyPageProofContext, legacy_page_proof


def _arguments() -> argparse.Namespace:
    """Require explicit local-test opt-in and a new direct /private/tmp output."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-local-page-ab", action="store_true", required=True)
    parser.add_argument("--page", required=True)
    parser.add_argument("--expected-json", required=True)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--ffprobe", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=180)
    parser.add_argument("--order", choices=("old-first", "new-first"), default="old-first")
    parser.add_argument("--expect-rejection", action="store_true")
    parser.add_argument("--expected-new-error")
    args = parser.parse_args()
    if not 0 < args.timeout_seconds <= 600:
        parser.error("test allowance must be finite and within 600 seconds")
    if args.expect_rejection and (not args.expected_new_error
            or not args.expected_new_error.startswith("caption page ")
            or len(args.expected_new_error) > 200):
        parser.error("negative tests require an exact caption-page error prefix")
    if args.expected_new_error and not args.expect_rejection:
        parser.error("an expected error is only valid for an explicit negative test")
    return args


def _paths(args: argparse.Namespace) -> tuple[Path, dict]:
    """Refuse symlinks/relative paths and publication into an existing source tree."""
    for token in (args.page, args.expected_json, args.ffmpeg, args.ffprobe):
        if not Path(token).is_absolute() or str(Path(token).resolve(strict=True)) != token:
            raise RuntimeError("TEST A/B requires canonical absolute existing inputs/tools")
    output = Path(args.output)
    if not output.is_absolute() or output.parent != Path("/private/tmp") \
            or output.name in {".", "..", ""}:
        raise RuntimeError("TEST A/B output must be a new direct child of /private/tmp")
    output.mkdir(mode=0o700, exist_ok=False)
    tools = {name: {"path": getattr(args, name)} for name in ("ffmpeg", "ffprobe")}
    return output, tools


def _held(args: argparse.Namespace, deadline: TestPageDeadline) -> tuple[dict, dict]:
    """Bind same input, tools, comparator and actual imported proof implementation."""
    modules = (decoder, proof_parser, progress_parser, process_runner, process_deadline)
    paths = [args.page, args.expected_json, args.ffmpeg, args.ffprobe, __file__]
    paths += [str(Path(__file__).with_name(name)) for name in
              ("_caption_page_ab_support.py", "_caption_page_legacy_proof.py")]
    paths += [str(Path(module.__file__).resolve()) for module in modules]
    observations = {path: file_observation(path, deadline.remaining) for path in paths}
    facts = expected_json(args.expected_json, observations[args.expected_json], deadline.remaining)
    if not isinstance(facts, dict) or set(facts) != {
            "codec_name", "pix_fmt", "width", "height", "r_frame_rate", "nb_read_frames"}:
        raise RuntimeError("TEST expected facts must have the exact page-proof stream shape")
    deadline.remaining()
    return observations, facts


def _leg(label: str, context: dict) -> dict:
    """Keep each attempt, its exception and time; never silently rerun a leg."""
    recorder = PageCommandRecorder(context["output"], str(Path(context["page"]).parent), label)
    started = time.monotonic()
    try:
        proof = _proof(label, context, recorder)
        context["deadline"].remaining()
        return {"status": "complete", "proof": proof, "commands": recorder.rows,
                "elapsedMs": (time.monotonic() - started) * 1000}
    except Exception as error:
        return {"status": "failed", "commands": recorder.rows,
                "error": {"type": type(error).__name__, "message": str(error)[:4000]},
                "elapsedMs": (time.monotonic() - started) * 1000}


def _proof(label: str, context: dict, recorder: PageCommandRecorder) -> dict:
    """Invoke exactly the requested algorithm; no inferred fallback or new budget."""
    if label == "old":
        return legacy_page_proof(context["page"], LegacyPageProofContext(
            context["facts"], context["tools"], recorder.old_command))
    with patch.object(decoder, "run_text", recorder):
        return decoder.decode_caption_page(context["page"], context["tools"], context["facts"])


def _equivalent(output: Path, results: dict) -> None:
    """Require exact result/type equality AND the entire raw framemd5 stdout bytes."""
    if any(row["status"] != "complete" for row in results.values()):
        raise RuntimeError("TEST positive A/B leg failed; exact equivalence not established")
    if results["old"]["proof"] != results["new"]["proof"] \
            or any(type(row["proof"]["alphaMax"]) is not float for row in results.values()):
        raise RuntimeError("TEST proof dictionary or alpha float type differs")
    if (output / "old-01.stdout").read_bytes() != (output / "new-01.stdout").read_bytes():
        raise RuntimeError("TEST complete framemd5 raw bytes differ")


def _execute(args: argparse.Namespace, output: Path, tools: dict,
             deadline: TestPageDeadline) -> dict:
    """Compare under one unchanged deadline and rehash every held byte afterward."""
    started = deadline.expires_at - args.timeout_seconds
    report = {"scope": "TEST-only-page-proof-equivalence-not-creative-or-source-approval"}
    with use_process_deadline(deadline):
        held, facts = _held(args, deadline)
        report["initialObservationMs"] = (time.monotonic() - started) * 1000
        report["held"] = held
        context = {"page": args.page, "facts": facts, "tools": tools, "output": output, "deadline": deadline}
        first = "old" if args.order == "old-first" else "new"
        results = {first: _leg(first, context)}
        other = "new" if args.order == "old-first" else "old"
        results[other] = _leg(other, context)
        report["legs"] = results
        _final(args, output, report, deadline)
        report["totalElapsedMs"] = (time.monotonic() - started) * 1000
        deadline.remaining()
    return report


def _final(args: argparse.Namespace, output: Path, report: dict,
           deadline: TestPageDeadline) -> None:
    """Retain observed failures before final checks; no failure is relabeled success."""
    write_json(output / "attempts.json", report)
    started = time.monotonic()
    current = {path: file_observation(path, deadline.remaining) for path in report["held"]}
    report["finalObservationMs"] = (time.monotonic() - started) * 1000
    if current != report["held"]:
        raise RuntimeError("TEST A/B input/tool/implementation bytes or identity changed")
    if args.expect_rejection:
        _expected_rejection(args.expected_new_error, report["legs"]["new"])
    else:
        _equivalent(output, report["legs"])
    deadline.remaining()


def _expected_rejection(prefix: str, result: dict) -> None:
    """Timeout/overflow/setup failure is not decoded defect-recall evidence."""
    error = result.get("error", {})
    if result["status"] != "failed" or error.get("type") != "RuntimeError" \
            or not error.get("message", "").startswith(prefix):
        raise RuntimeError("TEST exact requested semantic rejection was not observed")


def main() -> int:
    """Run only on explicit CLI opt-in, retaining terminal errors in a fresh root."""
    args = _arguments()
    deadline = TestPageDeadline(time.monotonic() + args.timeout_seconds)
    output, tools = _paths(args)
    print(str(output), flush=True)
    try:
        result = _execute(args, output, tools, deadline)
        write_json(output / "result.json", {"status": "TEST-check-passed", **result})
        deadline.remaining()
        return 0
    except BaseException as error:
        write_json(output / "failed.json", {"type": type(error).__name__, "message": str(error)[:4000]})
        raise


if __name__ == "__main__":
    sys.exit(main())
