"""Render an exact, source-proofed, private dialogue-stem generation.

This module has no legacy-plan, review-candidate, or promotion side effects.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile

from audio.dialogue_stem_contracts import (
    DialogueStemRenderError,
    DialogueStemRenderRequest,
    validate_dialogue_stem_request,
)
from audio.dialogue_stem_media import (
    OUTPUT_NAME,
    decode_sources,
    render_raw_entries,
)
from audio.dialogue_stem_mix import render_mix
from audio.dialogue_stem_probe import (
    assert_source_stable,
    require_rubberband,
)
from audio.dialogue_stem_publish import (
    RECEIPT_NAME,
    publish_generation,
)
from audio.dialogue_stem_receipt import (
    DialogueStemReceiptInput,
    build_dialogue_stem_receipt,
    verify_dialogue_stem_receipt,
    write_dialogue_stem_receipt,
)
from fingerprints import file_sha256


def _relax_children(path: str) -> None:
    for name in os.listdir(path):
        child = os.path.join(path, name)
        if not os.path.islink(child):
            os.chmod(child, 0o600, follow_symlinks=False)


def _cleanup_private(path: str, parent: str, prefix: str) -> None:
    if not os.path.lexists(path):
        return
    safe = os.path.dirname(path) == parent \
        and os.path.basename(path).startswith(prefix)
    if not safe:
        raise DialogueStemRenderError(
            "refusing to clean an unowned dialogue staging path")
    try:
        os.chmod(path, 0o700, follow_symlinks=False)
        _relax_children(path)
    except OSError:
        pass
    shutil.rmtree(path, ignore_errors=True)


def _published_leaf(path: str, expected_mode: int) -> None:
    if os.path.islink(path):
        raise DialogueStemRenderError(
            "published dialogue generation contains an alias")
    try:
        info = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise DialogueStemRenderError(
            "published dialogue generation is unreadable") from exc
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 \
            or stat.S_IMODE(info.st_mode) != expected_mode:
        raise DialogueStemRenderError(
            "published dialogue generation leaf is not sealed")


def _verify_publication(generation_dir: str, receipt: dict) -> None:
    directory = os.stat(generation_dir, follow_symlinks=False)
    if not stat.S_ISDIR(directory.st_mode) \
            or stat.S_IMODE(directory.st_mode) != 0o500:
        raise DialogueStemRenderError(
            "published dialogue generation directory is not sealed")
    output = os.path.join(generation_dir, OUTPUT_NAME)
    receipt_path = os.path.join(generation_dir, RECEIPT_NAME)
    _published_leaf(output, 0o400)
    _published_leaf(receipt_path, 0o400)
    if file_sha256(output) != receipt["output"]["sha256"]:
        raise DialogueStemRenderError(
            "published dialogue stem bytes changed")
    try:
        with open(receipt_path, encoding="utf-8") as handle:
            observed = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise DialogueStemRenderError(
            "published dialogue receipt cannot be read") from exc
    if observed != receipt:
        raise DialogueStemRenderError(
            "published dialogue receipt bytes changed")
    verify_dialogue_stem_receipt(observed)


def render_dialogue_stem(
    request: DialogueStemRenderRequest,
) -> dict[str, object]:
    """Compile, render, prove, seal, and atomically publish one stem."""
    validated = validate_dialogue_stem_request(request)
    require_rubberband(validated.tools)
    parent = os.path.dirname(validated.generation_dir)
    work = tempfile.mkdtemp(prefix=".sniper-dialogue-work-", dir=parent)
    stage = tempfile.mkdtemp(prefix=".sniper-dialogue-stage-", dir=parent)
    try:
        decoded = decode_sources(validated, work)
        entries, entry_proofs = render_raw_entries(
            validated, decoded, work)
        output_path, output_proof = render_mix(
            validated, entries, work, stage)
        for source in decoded:
            assert_source_stable(source)
        validated.tools.validate()
        receipt = build_dialogue_stem_receipt(DialogueStemReceiptInput(
            validated, decoded, entry_proofs, output_path, output_proof))
        write_dialogue_stem_receipt(
            os.path.join(stage, RECEIPT_NAME), receipt)
        publish_generation(stage, validated.generation_dir)
        _verify_publication(validated.generation_dir, receipt)
        for source in decoded:
            assert_source_stable(source)
        return receipt
    finally:
        _cleanup_private(work, parent, ".sniper-dialogue-work-")
        _cleanup_private(stage, parent, ".sniper-dialogue-stage-")
