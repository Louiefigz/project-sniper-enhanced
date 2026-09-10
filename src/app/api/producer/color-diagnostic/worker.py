"""Owned API entry: private diagnostics only, including observed cleanup facts."""
from __future__ import annotations

import json
import signal
import sys
from pathlib import Path


def _terminate(_signal: int, _frame: object) -> None:
    """Let diagnostic/container finally blocks run on the owner's one TERM."""
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    raise RuntimeError("color diagnostic owner requested bounded shutdown")


class CleanupTracker:
    """One unresolved source permanently prevents this job claiming cleanup."""

    def __init__(self) -> None:
        """Before any source invocation, no worker has been launched."""
        self.verified = True

    def record(self, previous: bool, observed: bool) -> None:
        """Aggregate with AND; later success cannot erase earlier uncertainty."""
        self.verified = previous and observed


def main() -> None:
    """Use only server-selected repository/input paths; never accept commands."""
    if len(sys.argv) != 3:
        raise SystemExit("server-owned diagnostic invocation required")
    repository, input_path = Path(sys.argv[1]).resolve(strict=True), Path(sys.argv[2])
    sys.path.insert(0, str(repository / "scripts/producer"))
    from color.diagnostic import run_diagnostic
    from color.model import DiagnosticRequest
    from cut_preview_io import read_bytes
    from headless.color_diagnostic_policy import ColorIsolationError, run_isolated
    row = json.loads(read_bytes(input_path, 2 * 1024 * 1024).decode("utf8"))["request"]
    clean = CleanupTracker()

    def run_source(source: str, request: dict) -> dict:
        """Record cleanup on every source, independently of analysis success."""
        previous, clean.verified = clean.verified, False
        try:
            value = run_isolated(source, request)
            clean.record(previous, value["removal"].get("canonicalAbsenceProved") is True)
            return value
        except ColorIsolationError as exc:
            clean.record(previous, exc.cleanup_verified)
            raise

    signal.signal(signal.SIGTERM, _terminate)
    try:
        request = DiagnosticRequest(Path(row["dir"]), row["expectedPlanHash"],
                                    row["expectedManifestHash"], row["contexts"], sample_budget=64)
        result = run_diagnostic(request, run_source)
        output = {"diagnosticId": result["diagnosticId"], "cleanupVerified": clean.verified}
    except (OSError, RuntimeError, ValueError, KeyError, TypeError):
        output = {"diagnosticId": None, "cleanupVerified": clean.verified}
    print(json.dumps(output, allow_nan=False))


if __name__ == "__main__":
    main()
