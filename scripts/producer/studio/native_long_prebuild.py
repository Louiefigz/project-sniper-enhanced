"""Bind Long editorial review to all authored/media bytes using the shared review validator."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from cross_runtime_canonical_json import canonical_compact_json
from studio.native_preflight_inputs import inventory
from studio.native_runtime import REPO, digest
from studio.native_stage_evidence import require, verify_pins
from studio.native_reference_reuse import bind_reference_map, declared_long_reference

REVIEW_FILE = 'PREBUILD-REVIEW.json'


def prebuild_snapshot(project: Path) -> dict:
    """Provide the reviewer a stable project digest without a receipt/hash cycle."""
    files, _directories = inventory(project)
    # PROJECT-MANIFEST is a generated file index, validated independently if used.
    excluded = {project / REVIEW_FILE, project / 'PROJECT-MANIFEST.json'}
    pins = {str(file): digest(file) for file in files if file not in excluded}
    relative = {str(Path(file).relative_to(project)): sha for file, sha in pins.items()}
    mapped = bind_reference_map({'adapter': 'native-long', 'project': str(project), 'pins': pins},
                                declared_long_reference(project))
    reference = mapped.get('referenceMap')
    binding = {'files': relative, 'referencePins': mapped['pins']} if reference else relative
    return {'scope': 'native-long-full-project', 'project': str(project), 'files': relative,
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


def require_long_prebuild(project: Path, tools: dict, environment: dict) -> dict:
    """Reject absent, failed or stale recorded judgments before source/media work."""
    receipt = project / REVIEW_FILE
    require(receipt.is_file() and not receipt.is_symlink(),
            'New long export requires PREBUILD-REVIEW.json from a separate full-project review; '
            'native_export.py review-input PROJECT prints the exact review binding')
    from graphics.visual_source_project import admit_project_sources
    admit_project_sources(project)
    snapshot = prebuild_snapshot(project)
    receipt_sha = digest(receipt)
    command = [tools['node'], '--import', 'tsx', str(REPO / 'scripts/producer/native-short.ts'),
               'check-long-review', str(receipt), snapshot['planHash']]
    completed = subprocess.run(command, cwd=REPO, env=environment, check=True,
                               capture_output=True, text=True, timeout=60)
    review = json.loads(completed.stdout)
    require(review['planHash'] == snapshot['planHash'] and digest(receipt) == receipt_sha,
            'Long prebuild review changed during admission')
    evidence = {row['path']: row['sha256'] for row in review['evidence']}
    require(all(file not in snapshot['pins'] or snapshot['pins'][file] == sha for file, sha in evidence.items()),
            'Long review evidence conflicts with snapshotted inputs')
    verify_pins({**snapshot['pins'], **evidence})
    return {'status': 'recorded-independent-plan-pass', 'planHash': snapshot['planHash'],
            'referenceMap': snapshot['referenceMap'],
            'independence': 'reviewer-declared-not-authenticated',
            'pins': {**snapshot['pins'], str(receipt): receipt_sha, **evidence}}
