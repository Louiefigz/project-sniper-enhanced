"""Admit selected media for native export without changing canonical source cuts."""
from __future__ import annotations

from fractions import Fraction
from pathlib import Path

from cut_preview_io import bound_json, file_hash
from edit.selected_sources import read_package
from studio.native_stage_evidence import MAX_NATIVE_FILE_BYTES, require


def prepared_source_pins(plan: dict) -> dict[str, str]:
    """Retain original source identity and the full immutable preparation closure."""
    if not plan.get('preparedSources'):
        return {}
    result, pins = read_package(plan['preparedSources'])
    originals = {(row['file'], row['path'], row['sha256']) for row in plan['assets']}
    require(all((row['file'], row['path'], row['sha256']) in originals
                for row in result['selection']['sources']), 'prepared source substituted original evidence')
    return pins


def dialogue_inputs(project: Path, canvas: dict) -> tuple[list[str], list[tuple[int, str]]]:
    """Use prepared per-cut float audio, with explicit legacy project compatibility."""
    plan_path = project / 'SHORT-PROJECT.json'
    plan = bound_json(plan_path) if plan_path.exists() else {}
    if not plan.get('preparedSources'):
        return ['-i', str(project / canvas['sourceFile'])], [(0, str(row['start'])) for row in canvas['cuts']]
    require(plan['canvas'] == canvas, 'dialogue canvas differs from the admitted prepared project')
    report = bound_json(project / 'PREPARED-SOURCES.json')
    require(report['package'] == plan['preparedSources'], 'dialogue package binding changed')
    rows = [row for row in report['mappings'] if row['kind'] == 'audio']
    require(len(rows) == len(canvas['cuts']), 'prepared dialogue inventory differs from source cuts')
    mappings = {row['id']: row for row in rows}
    require(len(mappings) == len(rows), 'prepared dialogue IDs duplicate')
    manifest = bound_json(project / 'PROJECT-MANIFEST.json')
    hashes = {row['file']: row['sha256'] for row in manifest['files']}
    inputs, cuts = [], []
    for index, cut in enumerate(canvas['cuts']):
        row = mappings.get(f'dialogue-{index}')
        require(row is not None and row['sourceFile'] == canvas['sourceFile']
                and row['start'] == cut['start'], 'prepared dialogue changed a source cut')
        file = project / row['preparedFile']
        require(file.suffix == '.wav' and file.is_relative_to(project / 'assets')
                and file_hash(file, MAX_NATIVE_FILE_BYTES) == hashes.get(row['preparedFile']),
                'prepared dialogue file changed or escaped its project')
        local = Fraction(str(cut['start'])) - Fraction(row['sourceOrigin'])
        require(local >= 0 and abs(float(local) - row['mediaStart']) < 1e-9,
                'prepared dialogue lost its original source offset')
        inputs += ['-i', str(file)]
        cuts.append((index, format(float(local), '.12f')))
    return inputs, cuts
