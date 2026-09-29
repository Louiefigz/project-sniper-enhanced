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


def require_typed_short_reviews(file: Path, project: Path) -> None:
    """Cheap pre-reservation check for a native Short: every row is typed and, when rows exist, one approves motion.

    Runs in option validation, before the production budget reserves (and charges) the launch, so a bundle recorded
    before typed review evidence, or a picture-only pass, is refused without cost. A route-canary TEST fixture
    declaration never admits a project a production batch budgets. The TS reader still decides the full admission
    (coverage, bytes, provenance, the fixture layout, and an empty bundle) after reservation.
    """
    bundle = bound_json(file)
    rows = bundle.get('reviews') if isinstance(bundle, dict) else None
    require(isinstance(rows, list), 'Native motion review bundle has no review list')
    if not rows:
        return
    fixtures = [index for index, row in enumerate(rows) if isinstance(row, dict) and isinstance(row.get('inspection'), dict)
                and row['inspection'].get('fixture') is not None]
    if fixtures:
        from studio.native_budget_registry import resolve_binding
        from studio.native_budget_store import default_root
        require(resolve_binding(default_root(), project) is None,
                f'motion review rows {fixtures} are route-canary TEST fixture declarations, and a production batch '
                'budgets this project; a fixture never admits production work. Refused before any budget reservation')
    untyped = [index for index, row in enumerate(rows) if not isinstance(row, dict) or not isinstance(row.get('inspection'), dict)]
    require(not untyped, f'motion review rows {untyped} carry no typed inspection (recorded before typed review '
            'evidence); a native Short needs a typed motion review from context.py --role motion-critic. Refused '
            'before any budget reservation')
    require(any('motion' in (row['inspection'].get('approves') or []) for row in rows),
            'no row approves motion (typed normal-speed playback of every window); stills-only reviews admit no full '
            'picture. Refused before any budget reservation')


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
