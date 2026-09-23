"""Bounded discovery and transitive validation of completed moving-preview evidence."""
from __future__ import annotations

from pathlib import Path

from cut_preview_io import bound_json
from studio.native_export_history import candidate_attempts
from studio.native_review_regions import preview_windows
from studio.native_runtime import digest
from studio.native_stage_evidence import require

STATUS = 'native-motion-previews-complete'


def preview_record(file: Path, project: str) -> dict:
    """Require an immutable request and completed shared owner for every retained clip."""
    value = bound_json(file)
    owner = bound_json(file.parent / 'preview.render.json')
    request_file = file.parent / 'export-request.json'
    request = bound_json(request_file)
    require(value.get('status') == STATUS and value['packet']['project'] == project
            and owner.get('status') == STATUS and owner.get('output') == str(file)
            and owner.get('exitCode') == 0 and isinstance(owner.get('completedAt'), str)
            and owner.get('cleanup', {}).get('verified') is True
            and owner.get('cleanup', {}).get('survivors') == []
            and owner.get('additionalFilePinsBefore', {}).get(str(request_file)) == digest(request_file)
            and request['project'] == project and request['output'] == str(file.parent)
            and value.get('priorPreview') == request.get('previewFrom'),
            'Prior preview lacks its completed shared owner')
    for clip in value['clips']:
        require(digest(Path(clip['path'])) == clip['sha256'], 'Prior preview media changed')
    return value


def preview_chain(file: Path, project: str) -> list[tuple[Path, dict]]:
    """Check ancestors too: unchanged units cannot survive a missing original preview."""
    chain: list[tuple[Path, dict]] = []
    seen: set[Path] = set()
    while file:
        require(file.is_absolute() and file.resolve() == file and file not in seen
                and len(chain) < 64, 'Preview history is cyclic, noncanonical or exceeds 64 revisions')
        seen.add(file)
        value = preview_record(file, project)
        chain.append((file, value))
        previous = Path(value['priorPreview']) if value.get('priorPreview') else None
        if previous:
            request = bound_json(file.parent / 'export-request.json')
            require(request.get('pins', {}).get(str(previous)) == digest(previous), 'Prior preview ancestor changed')
        file = previous
    for index, (_file, value) in enumerate(chain):
        previous = chain[index + 1][1]['packet'] if index + 1 < len(chain) else None
        expected = [[row['startFrame'], row['endFrame']] for row in preview_windows(value['packet'], previous)]
        require([row['absoluteFrameRange'] for row in value['clips']] == expected,
                'Prior preview chain omits required changed regions')
    return chain


def prior_preview(file: Path, project: str) -> dict:
    """Return the most recent record only after validating its complete evidence chain."""
    return preview_chain(file, project)[0][1]


def discover_preview(request: dict) -> Path | None:
    """Select the latest completed same-project preview from bounded export history."""
    candidates = []
    for attempt in candidate_attempts(request):
        file, delivery = attempt / 'motion-previews.json', attempt / 'delivery.json'
        if not file.is_file() or not delivery.is_file():
            continue
        previous = bound_json(attempt / 'export-request.json')
        if previous.get('project') != request['project']:
            continue
        completed = bound_json(delivery).get('completedAt')
        if isinstance(completed, str):
            candidates.append((completed, str(file)))
    if not candidates:
        return None
    selected = Path(max(candidates)[1])
    prior_preview(selected, request['project'])
    return selected
