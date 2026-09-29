#!/usr/bin/env python3
"""Prepare or reopen one owned complete-program premaster for native projects."""
from __future__ import annotations

import argparse
import json
import os
import stat
from pathlib import Path

from audio.native_program_audio import prepare_native_program_audio, publish_float_copy
from audio.program_audio_clock import exact_float_audio_clock
from cut_preview_io import bound_json, digest, file_hash, write_new
from studio.native_stage_evidence import require
from studio.owned_inspection import read_inspection, require_worker, run_inspection

HERE = Path(__file__).resolve()
PUBLIC_NAME = "native-program-audio.json"
INSTALL_NAME = "PROGRAM-AUDIO.json"


def _current(request: dict) -> None:
    """Require exact unchanged controller documents at every media boundary."""
    require(bound_json(Path(request["planPath"])) == request["plan"],
            "Native program audio plan changed")
    require(bound_json(Path(request["manifestPath"])) == request["manifest"],
            "Native program audio manifest changed")
    body = {key: request[key] for key in ("project", "planPath", "manifestPath", "plan", "manifest")}
    require(request["inputHash"] == digest(body), "Native program audio input authority changed")


def worker(file: Path) -> None:
    """Execute media only under the shared resource owner and immutable request."""
    request = require_worker(file, HERE)
    _current(request)
    result = prepare_native_program_audio(request, file.parent)
    _current(request)
    require_worker(file, HERE)
    write_new(file.parent / "result.json", result)


def _audio_path(reference: dict, record: dict) -> Path:
    """Confine the retained WAV to the exact completed owner directory."""
    root = Path(reference["path"]).parent.resolve(strict=True)
    path = Path(record["audio"]["path"])
    require(path == root / "program.wav" and path.resolve(strict=True) == path,
            "Native program audio escaped its completed owner")
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode)
            and info.st_nlink == 1, "Native program audio is not one regular unaliased file")
    return path


def read_preparation(reference: dict, request: dict) -> dict:
    """Reobserve completed ownership, current inputs, bytes, and exact float clock."""
    _current(request)
    record = read_inspection(reference)
    body = {key: value for key, value in record.items() if key != "receiptHash"}
    expected = {"kind": "native-program-audio-authority",
        "status": "native-program-audio-prepared",
        "scope": "complete-program-native-premaster-not-review-or-delivery",
        "project": request["project"], "humanListeningApproved": False,
        "nativeExportApproved": False}
    require(record.get("schemaVersion") == 1 and record.get("receiptHash") == digest(body)
            and all(record.get(key) == value for key, value in expected.items()),
            "Native program audio authority is malformed")
    require(record.get("plan") == {"path": request["planPath"],
                "sha256": file_hash(Path(request["planPath"]))}
            and record.get("manifest", {}).get("path") == request["manifestPath"]
            and record.get("manifest", {}).get("sha256") == file_hash(Path(request["manifestPath"])),
            "Native program audio authority differs from current inputs")
    audio, path = record.get("audio", {}), _audio_path(reference, record)
    require(audio.get("sha256") == file_hash(path)
            and audio.get("sizeBytes") == path.stat().st_size,
            "Native program WAV bytes changed")
    observed = exact_float_audio_clock(str(path), record["tools"]["ffprobe"]["path"],
                                       audio.get("samples"))
    require(all(audio.get(key) == value for key, value in observed.items()),
            "Native program WAV float clock changed")
    _current(request)
    return record


def _request(producer: Path, manifest: Path) -> dict:
    """Freeze the canonical plan and manifest used by the owned worker."""
    plan = producer / "edit_plan.json"
    body = {"project": str(producer), "planPath": str(plan),
        "manifestPath": str(manifest), "plan": bound_json(plan),
        "manifest": bound_json(manifest)}
    return {**body, "inputHash": digest(body)}


def _public(file: Path, request: dict, project: Path) -> dict:
    """Reopen one resumable public pointer without minting review or delivery."""
    value = bound_json(file)
    body = {key: item for key, item in value.items() if key != "digest"}
    require(value.get("schemaVersion") == 1 and value.get("kind") == "native-program-audio-preparation"
            and value.get("digest") == digest(body) and value.get("inputHash") == request["inputHash"]
            and value.get("project") == str(project),
            "Native program audio resume pointer is stale or malformed")
    record = read_preparation(value["authority"], request)
    installed = install_native_program_audio(project, request, value["authority"], record)
    expected = {"path": str(project / INSTALL_NAME),
        "sha256": file_hash(project / INSTALL_NAME), "receiptHash": installed["receiptHash"]}
    require(value.get("installation") == expected,
            "Native program audio public installation binding changed")
    return value


def _installation(project: Path, request: dict, authority: dict, record: dict) -> dict:
    """Describe one project-local file selected only by the controller authority."""
    source, target = Path(record["audio"]["path"]), project / "assets" / "program.wav"
    target.parent.mkdir(mode=0o700, exist_ok=True)
    if target.parent.resolve(strict=True) != target.parent or target.parent.is_symlink():
        raise RuntimeError("Native program audio asset directory is unsafe")
    if target.exists():
        if target.is_symlink() or file_hash(target) != record["audio"]["sha256"]:
            raise RuntimeError("Native project contains a different program WAV")
    else:
        publish_float_copy(source, target, record["audio"]["sha256"])
    body = {"schemaVersion": 1, "kind": "native-program-audio-installation",
        "scope": record["scope"], "inputHash": request["inputHash"],
        "authority": {"path": authority["path"], "sha256": authority["sha256"],
            "owner": authority["owner"], "ownerSha256": authority["ownerSha256"],
            "receiptHash": record["receiptHash"]},
        "audio": {**record["audio"], "path": str(target), "file": "assets/program.wav"},
        "humanListeningApproved": False, "nativeExportApproved": False}
    return {**body, "receiptHash": digest(body)}


def install_native_program_audio(project: Path, request: dict,
                                 authority: dict, record: dict) -> dict:
    """Install or reopen the exact prepared WAV and immutable project receipt."""
    if project.resolve(strict=True) != project or project.is_symlink():
        raise RuntimeError("Native project directory must be canonical and unlinked")
    expected = _installation(project, request, authority, record)
    receipt = project / INSTALL_NAME
    if receipt.exists():
        require(bound_json(receipt) == expected, "Native program audio installation changed")
    else:
        write_new(receipt, expected)
    return expected


def _installed_audio(project: Path, value: dict, record: dict) -> Path:
    """Reobserve the project copy as one canonical unaliased float WAV."""
    path = project / "assets" / "program.wav"
    audio = value.get("audio", {})
    require(audio.get("path") == str(path) and audio.get("file") == "assets/program.wav"
            and path.resolve(strict=True) == path, "Native program audio is not project-local")
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode)
            and info.st_nlink == 1 and audio.get("sizeBytes") == info.st_size
            and audio.get("sha256") == file_hash(path) == record["audio"]["sha256"],
            "Installed native program WAV bytes changed")
    observed = exact_float_audio_clock(str(path), record["tools"]["ffprobe"]["path"],
                                       audio.get("samples"))
    require(all(audio.get(key) == item for key, item in observed.items()),
            "Installed native program WAV float clock changed")
    return path


def read_native_program_audio_installation(project: Path, producer: Path,
                                           manifest: Path) -> dict:
    """Validate current inputs, completed ownership, receipt, local bytes and clock."""
    request = _request(producer, manifest)
    receipt = project / INSTALL_NAME
    value = bound_json(receipt)
    authority = value.get("authority", {})
    require(set(authority) == {"path", "sha256", "owner", "ownerSha256", "receiptHash"},
            "Native program audio installation lacks its owned authority")
    record = read_preparation(authority, request)
    require(authority["receiptHash"] == record["receiptHash"],
            "Native program audio authority receipt changed")
    _installed_audio(project, value, record)
    expected = _installation(project, request, authority, record)
    require(value == expected, "Native program audio installation changed")
    return value


def prepare(producer: Path, manifest: Path, project: Path, output: Path) -> dict:
    """Run once or resume exact completed bytes from the same attempt directory."""
    request = _request(producer, manifest)
    public = output / PUBLIC_NAME
    if output.exists():
        value = _public(public, request, project)
        return {**value, "status": "native-program-audio-reused"}
    output.mkdir(mode=0o700)
    authority = run_inspection(HERE, output / "owned", request)
    record = read_preparation(authority, request)
    installation = install_native_program_audio(project, request, authority, record)
    body = {"schemaVersion": 1, "kind": "native-program-audio-preparation",
        "status": "native-program-audio-prepared", "inputHash": request["inputHash"],
        "project": str(project), "authority": authority, "audio": record["audio"],
        "installation": {"path": str(project / INSTALL_NAME),
            "sha256": file_hash(project / INSTALL_NAME), "receiptHash": installation["receiptHash"]},
        "humanListeningApproved": False, "nativeExportApproved": False}
    value = {**body, "digest": digest(body)}
    write_new(public, value)
    return value


def main() -> None:
    """CLI entry point with no provider-controlled audio input."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("producer", nargs="?", type=Path)
    parser.add_argument("manifest", nargs="?", type=Path)
    parser.add_argument("project", nargs="?", type=Path)
    parser.add_argument("output", nargs="?", type=Path)
    parser.add_argument("--worker", type=Path)
    args = parser.parse_args()
    if args.worker:
        worker(args.worker)
        return
    if not all((args.producer, args.manifest, args.project, args.output)):
        parser.error("producer directory, manifest, native project, and preparation output are required")
    result = prepare(args.producer.resolve(strict=True), args.manifest.resolve(strict=True),
                     args.project.resolve(strict=True), args.output.absolute())
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
