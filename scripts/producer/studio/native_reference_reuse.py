"""Opt-in reference-match planning evidence shared by native Short and Long checks."""
from __future__ import annotations

from pathlib import Path

from graphics.catalog_discovery import load_catalog
from graphics.reference_reuse_map import read_checked_map
from cut_preview_io import bound_json

PRODUCER = Path(__file__).resolve().parents[1]


def implementation_files() -> list[Path]:
    """Retain the shared mapper and discovery implementation in native input pins."""
    graphics = PRODUCER / 'graphics'
    return [*graphics.glob('reference_reuse*.py'), *graphics.glob('catalog_discovery*.py'),
            PRODUCER / 'cross_runtime_canonical_json.py', PRODUCER / 'cut_preview_io.py']


def reference_snapshot(project: Path, file: Path | None, expected_format: str | None = None) -> dict | None:
    """Check only an explicitly supplied map against its intended native project."""
    if file is None:
        return None
    snapshot = read_checked_map(file, load_catalog())
    report = snapshot['report']
    if report['project'] != str(project):
        raise ValueError('Reference reuse map belongs to a different native project')
    if report['ready'] is not True:
        raise ValueError('Reference matching has unresolved prerequisites; inspect its reuse map')
    if expected_format is not None and report['format'] != expected_format:
        raise ValueError(f'Native export requires a {expected_format} reference map')
    return snapshot


def _merge_pins(existing: dict[str, str], snapshot: dict) -> dict[str, str]:
    """Add planning evidence without replacing previously admitted input hashes.

    A reference or shot plan may itself be an existing project input. A change
    between the two reads must fail rather than silently adopt the newer bytes.
    """
    additions = {**snapshot['report']['inputPins'], snapshot['path']: snapshot['sha256']}
    for path, sha256 in additions.items():
        if path in existing and existing[path] != sha256:
            raise ValueError(f'Reference evidence conflicts with an admitted native input: {path}')
    return {**existing, **additions}


def bind_reference_map(request: dict, file: Path | None) -> dict:
    """Bind selected planning evidence to the declared export format's dependency map."""
    expected_format = 'longform' if request.get('adapter') == 'native-long' else 'short'
    snapshot = reference_snapshot(Path(request['project']), file, expected_format)
    if snapshot is None:
        return request
    pins = _merge_pins(request['pins'], snapshot)
    return {**request, 'referenceMap': snapshot['path'], 'pins': pins}


def declared_long_reference(project: Path) -> Path | None:
    """Persist explicit reference matching in the authored plan so export cannot forget a flag."""
    plan = project / 'LONG-PROJECT.json'
    record = bound_json(plan) if plan.exists() else {}
    if 'referenceMap' not in record:
        return None
    value = record['referenceMap']
    if not isinstance(value, str) or not value or len(value) > 4096 or any(c in value for c in '\0\r\n'):
        raise ValueError('Long referenceMap requires a canonical absolute map path')
    file = Path(value)
    if not file.is_absolute() or file.resolve(strict=True) != file or file.is_symlink():
        raise ValueError('Long referenceMap requires a canonical absolute map path')
    return file
