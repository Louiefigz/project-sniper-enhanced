"""Read-only comparison of distinct old/new1080p cohorts; never launches media."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path

from _presenter_benchmark_comparison import compare_metadata, graph_declaration_record
from opening_prefix_contract import HeldPrefixInput, PrefixDeadline, verify_held_input, _identity
from opening_prefix_oracle import _frames


def read_bytes(path: Path, deadline: PrefixDeadline, maximum: int) -> bytes:
    """Read a bounded regular artifact; aliases and nonregular files never block reads."""
    deadline.remaining()
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= maximum:
            raise AssertionError("comparison JSON exceeds its size bound")
        data = os.read(descriptor, maximum + 1)
        if len(data) != before.st_size or _identity(os.fstat(descriptor)) != _identity(before) \
                or _identity(path.lstat()) != _identity(before):
            raise AssertionError("comparison artifact changed during read")
    finally:
        os.close(descriptor)
    deadline.remaining()
    return data


def read_json(path: Path, deadline: PrefixDeadline, maximum: int = 4 * 1024 * 1024) -> tuple[dict, str]:
    """Keep the exact raw JSON digest alongside the bounded parsed document."""
    data = read_bytes(path, deadline, maximum)
    return json.loads(data), hashlib.sha256(data).hexdigest()


def _frame_file(root: Path, command: dict, deadline: PrefixDeadline) -> tuple[str, ...]:
    """Verify complete actual framehash output; never repair missing or extra frames."""
    if command.get("returncode") != 0 or "error" in command:
        raise AssertionError("comparison framehash command was not completed")
    path = root / (command["name"] + ".stdout")
    data = read_bytes(path, deadline, 65536)
    count = 30 if command["stage"].endswith("output-qc") else int(command["argv"][command["argv"].index("-frames:v") + 1])
    return _frames(data.decode(), (count, "30000/1001", 1920 * 1080 * 3 // 2))


def _new_frames(report: dict, root: Path, stage: str, deadline: PrefixDeadline) -> list[tuple[str, ...]]:
    """Select only real framehash commands, not stream metadata or status text."""
    rows = [row for row in report["commands"] if row["stage"] == stage and "-hash" in row["argv"]]
    return [_frame_file(root, row, deadline) for row in rows]


def compare_frames(index: dict, report: dict, root: Path, deadline: PrefixDeadline) -> dict:
    """All three existing encoded results and every completed old prefix must match."""
    encodes = {}
    for row in index["encodedOutputs"]:
        new = next(item for item in report["encodes"] if item["label"] == row["label"])
        output = new["output"]
        verify_held_input(HeldPrefixInput(output["path"], output["sha256"], output["sizeBytes"]), deadline)
        expected = tuple(row["frameHashes"])
        actual = _new_frames(report, root, row["label"] + "-output-qc", deadline)
        if len(expected) != 30 or actual != [expected]:
            raise AssertionError(f"all30 encoded frames differ for {row['label']}")
        encodes[row["label"]] = True
    if set(encodes) != {"baseline", "still", "video"}:
        raise AssertionError("comparison lacks all three encoded baseline references")
    prefixes = {}
    for stage in ("baseline-prefix", "still-prefix"):
        expected = [tuple(row["frameHashes"]) for row in index["preencodePrefixOutputs"] if row["stage"] == stage]
        if [len(row) for row in expected] != [30, 18, 30] or _new_frames(report, root, stage, deadline) != expected:
            raise AssertionError(f"complete retained preencode frames differ for {stage}")
        prefixes[stage] = True
    return {"all30NativeEncodedFramesEqual": encodes, "allCompletedOldPreencodeFramesEqual": prefixes}


def compare(index_reference: tuple[Path, str], new_root: Path, deadline: PrefixDeadline) -> dict:
    """Fail closed on any input, declaration, tool, timing, graph or pixel mismatch."""
    index_path, expected_sha = index_reference
    if re.fullmatch(r"[0-9a-f]{64}", expected_sha) is None:
        raise AssertionError("comparison requires separately held old index SHA256")
    index, index_sha = read_json(index_path, deadline)
    if index_sha != expected_sha:
        raise AssertionError("old comparison index changed from the independently held hash")
    old_path = Path(index["benchmarkReport"]["path"])
    old, old_sha = read_json(old_path, deadline)
    if old_sha != index["benchmarkReport"]["sha256"]:
        raise AssertionError("original failed benchmark report changed after index hold")
    new, new_sha = read_json(new_root / "TEST-benchmark-evidence.json", deadline)
    roots = (old_path.parent, new_root)
    metadata = compare_metadata(old, new, roots)
    old_proof, old_proof_sha = read_json(roots[0] / "still-prefix-proof.json", deadline)
    new_proof, new_proof_sha = read_json(roots[1] / "still-prefix-proof.json", deadline)
    if graph_declaration_record(old_proof, roots[0], "still") != graph_declaration_record(new_proof, roots[1], "still"):
        raise AssertionError("actual original presenter declarations differ")
    frames = compare_frames(index, new, new_root, deadline)
    deadline.remaining()
    return {"status": "equal", "scope": "distinct-TEST-sample-not-production-performance-approval", **metadata, **frames,
        "sameOriginalDeclarations": True, "pixelFormat": "yuv420p", "noMediaProcesses": True,
        "oldIndexSha256": index_sha, "oldReportSha256": old_sha, "newReportSha256": new_sha,
        "oldStillProofSha256": old_proof_sha, "newStillProofSha256": new_proof_sha,
        "newEncodes": new["encodes"], "newPrefixes": new["prefixes"], "tenMinuteOrTwoHourGuarantee": False}


def main() -> int:
    """Only inspect named retained roots under a separate fixed30s read-only clock."""
    deadline = PrefixDeadline(30)
    if len(sys.argv) != 4:
        print("Usage: compare_presenter_1080p.py OLD_INDEX_JSON EXPECTED_INDEX_SHA256 NEW_COHORT_ROOT", file=sys.stderr)
        return 2
    index, root = Path(sys.argv[1]).resolve(strict=True), Path(sys.argv[3]).resolve(strict=True)
    result = compare((index, sys.argv[2]), root, deadline)
    with (root / "TEST-pixel-comparison.json").open("x") as stream:
        stream.write(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "output": str(root / "TEST-pixel-comparison.json")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
