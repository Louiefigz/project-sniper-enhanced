"""Admit current region judgments without rerendering or rereviewing unchanged previews."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from cut_preview_io import bound_json, write_new
from studio.native_preview_history import preview_chain
from studio.native_runtime import REPO, digest
from studio.native_stage_evidence import require


def review_input_pins(file: Path, project: str) -> dict[str, str]:
    """Freeze all supplied review media and ancestors before any expensive owner starts."""
    bundle = bound_json(file)
    require(bundle.get('schemaVersion') == 1 and isinstance(bundle.get('reviews'), list)
            and len(bundle['reviews']) <= 256, 'Invalid native motion review bundle')
    pins = {str(file): digest(file)}
    for row in bundle['reviews']:
        preview = row['preview']
        require(digest(Path(preview['path'])) == preview['sha256'], 'Reviewed native preview changed')
        for source, value in preview_chain(Path(preview['path']), project):
            artifacts = [source, source.parent / 'preview.render.json', source.parent / 'export-request.json']
            pins.update({str(artifact): digest(artifact) for artifact in artifacts})
            pins.update({clip['path']: clip['sha256'] for clip in value['clips']})
        for evidence in row['evidence']:
            require(digest(Path(evidence['path'])) == evidence['sha256'], 'Motion review evidence changed')
            pins[evidence['path']] = evidence['sha256']
    return pins


def require_preview_review(request: dict, packet: dict) -> None:
    """Full picture cannot run on generated-but-unreviewed or stale preview evidence."""
    file = request.get('previewReviews')
    require(bool(file) and not request.get('previewOnly'),
            'Full native rendering needs independent moving-preview reviews; use --preview-reviews')
    require(digest(Path(file)) == request['pins'].get(file), 'Native preview review changed after admission')
    packet_file = Path(request['output']) / 'motion-review-input.json'
    if not packet_file.exists():
        write_new(packet_file, packet)
    require(bound_json(packet_file) == packet, 'Native review region packet changed')
    result = subprocess.run([request['tools']['node'], '--import', 'tsx',
        str(REPO / 'scripts/producer/native-short.ts'), 'check-motion-reviews', file, str(packet_file)],
        cwd=REPO, check=True, capture_output=True, text=True, timeout=60)
    checked = json.loads(result.stdout)
    require(checked.get('status') == 'recorded-independent-motion-pass', 'Native motion review did not pass')
    for pin in checked['pins']:
        require(request['pins'].get(pin['path']) == pin['sha256'] == digest(Path(pin['path'])),
                'Native motion review evidence was not frozen before export')
