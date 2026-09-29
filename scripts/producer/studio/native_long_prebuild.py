"""Bind Long editorial review to all authored/media bytes using the shared review validator."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from cut_preview_io import bound_json
from cross_runtime_canonical_json import canonical_compact_json
from studio.native_preflight_inputs import inventory
from studio.native_runtime import REPO, digest
from studio.native_stage_evidence import require, verify_pins
from studio.native_reference_reuse import bind_reference_map, declared_long_reference
from studio.native_style_application import validate_long_style_application
from studio.native_visual_plan_application import validate_long_visual_plan_application
from studio.native_long_contract import (require_current_long_policy,
                                         validate_current_long_program_audio)

REVIEW_FILE = 'PREBUILD-REVIEW.json'


def prebuild_snapshot(project: Path, section_scope: dict | None = None) -> dict:
    """Provide the reviewer a stable project digest without a receipt/hash cycle."""
    require_current_long_policy(project)
    files, _directories = inventory(project)
    # PROJECT-MANIFEST is a generated file index, validated independently if used.
    excluded = {project / REVIEW_FILE, project / 'PROJECT-MANIFEST.json'}
    pins = {str(file): digest(file) for file in files if file not in excluded}
    from studio.native_long_chunks import chunk_prebuild_pins
    pins.update(chunk_prebuild_pins(project))
    plan = project / 'LONG-PROJECT.json'
    document = bound_json(plan) if plan.exists() else {}
    if document.get('schemaVersion') == 2:
        audio_pins = validate_current_long_program_audio(project, document)
        for file, sha256 in audio_pins.items():
            require(file not in pins or pins[file] == sha256,
                    'Long program-audio evidence conflicts with project inputs')
        pins.update(audio_pins)
    style_pins = validate_long_style_application(project, document) if plan.exists() else {}
    for file, sha256 in style_pins.items():
        require(file not in pins or pins[file] == sha256,
                'Long style evidence conflicts with project inputs')
    pins.update(style_pins)
    visual_pins = (validate_long_visual_plan_application(project, document, section_scope)
                   if plan.exists() else {})
    for file, sha256 in visual_pins.items():
        require(file not in pins or pins[file] == sha256,
                'Long visual-plan evidence conflicts with project inputs')
    pins.update(visual_pins)
    relative = {str(Path(file).relative_to(project)): sha for file, sha in pins.items()
                if Path(file).is_relative_to(project)}
    external = {file: sha for file, sha in pins.items()
                if not Path(file).is_relative_to(project)}
    mapped = bind_reference_map({'adapter': 'native-long', 'project': str(project), 'pins': pins},
                                declared_long_reference(project))
    reference = mapped.get('referenceMap')
    binding: object = relative
    if external:
        binding = {'files': relative, 'externalPins': external}
    if reference:
        binding = {'files': relative, 'externalPins': external,
                   'referencePins': mapped['pins']}
    if section_scope is not None:
        binding = {'snapshot': binding, 'sectionScope': section_scope}
    return {'scope': 'native-long-section-snapshot' if section_scope else 'native-long-full-project',
            'project': str(project), 'files': relative,
            'referenceMap': reference,
            'planHash': hashlib.sha256(canonical_compact_json(binding).encode()).hexdigest(), 'pins': mapped['pins']}


def review_implementation_files() -> list[Path]:
    """Pin the shared TypeScript validator and its direct validation dependencies."""
    return [REPO / file for file in (
        'scripts/producer/native-short.ts', 'src/lib/server/native-short-prebuild-review.ts',
        'src/lib/server/native-motion-review.ts',
        'src/lib/server/auto-edit-hash.ts', 'src/lib/producer/contracts/validation.ts',
        'src/app/api/producer/auto-edit/review-contract.ts',
        'src/app/api/producer/auto-edit/cut-preview-receipt.ts')]


def require_long_prebuild(project: Path, tools: dict, environment: dict, section_scope: dict | None = None) -> dict:
    """Reject absent, failed or stale recorded judgments before source/media work."""
    receipt = project / REVIEW_FILE
    require(receipt.is_file() and not receipt.is_symlink(),
            'New long export requires PREBUILD-REVIEW.json from a separate full-project review; '
            'native_export.py review-input PROJECT prints the exact review binding')
    from graphics.visual_source_project import admit_project_sources
    admit_project_sources(project)
    snapshot = prebuild_snapshot(project, section_scope)
    receipt_sha = digest(receipt)
    command = [tools['node'], '--import', 'tsx', str(REPO / 'scripts/producer/native-short.ts'),
               'check-long-section-review' if section_scope else 'check-long-review',
               str(receipt), snapshot['planHash']]
    completed = subprocess.run(command, cwd=REPO, env=environment, check=True,
                               capture_output=True, text=True, timeout=60)
    review = json.loads(completed.stdout)
    from studio.native_long_chunks import require_chunk_review
    require_chunk_review(project, review)
    require(review['planHash'] == snapshot['planHash'] and digest(receipt) == receipt_sha,
            'Long prebuild review changed during admission')
    evidence = {row['path']: row['sha256'] for row in review['evidence']}
    require(all(file not in snapshot['pins'] or snapshot['pins'][file] == sha
                for file, sha in evidence.items()),
            'Long review evidence conflicts with snapshotted inputs')
    verify_pins({**snapshot['pins'], **evidence})
    return {'status': 'recorded-independent-plan-pass', 'scope': snapshot['scope'],
            'planHash': snapshot['planHash'],
            'referenceMap': snapshot['referenceMap'],
            'independence': 'reviewer-declared-not-authenticated',
            'pins': {**snapshot['pins'], str(receipt): receipt_sha, **evidence}}
