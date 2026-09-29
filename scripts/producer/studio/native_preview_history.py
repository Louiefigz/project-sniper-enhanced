"""Bounded discovery and transitive validation of completed moving-preview evidence.

Donor previews may come from the current project or from a verified ancestor in
its recorded clip lineage (``native_clip_lineage``); a schema-2 packet must name
the same logical clip, so another clip's media never qualifies. Each record still
needs its completed owner, immutable request, unchanged clips and a complete chain.
"""
from __future__ import annotations

from pathlib import Path

from cut_preview_io import bound_json
from studio.native_clip_lineage import lineage_projects, packet_subject
from studio.native_export_history import candidate_attempts, lineage_attempts
from studio.native_long_scope import request_preview_windows
from studio.native_runtime import digest
from studio.native_stage_evidence import require

STATUS = 'native-motion-previews-complete'


def preview_identity(project: str) -> tuple[set[str], dict]:
    """Admitted donor projects and the packet subject every donor record must share."""
    current = Path(project)
    return set(lineage_projects(current)), packet_subject(current)


def same_clip(packet: dict, project: str, subject: dict) -> bool:
    """Schema-2 packets compare logical subjects; schema-1 (Long) packets keep exact paths."""
    if packet.get('schemaVersion') == 2:
        return packet.get('subject') == subject
    return packet.get('project') == project


def preview_record(file: Path, project: str, identity: tuple[set[str], dict] | None = None) -> dict:
    """Require an immutable request and completed shared owner for every retained clip."""
    admitted, subject = identity or preview_identity(project)
    value = bound_json(file)
    owner = bound_json(file.parent / 'preview.render.json')
    request_file = file.parent / 'export-request.json'
    request = bound_json(request_file)
    require(value.get('status') == STATUS and same_clip(value['packet'], request['project'], subject)
            and owner.get('status') == STATUS and owner.get('output') == str(file)
            and owner.get('exitCode') == 0 and isinstance(owner.get('completedAt'), str)
            and owner.get('cleanup', {}).get('verified') is True
            and owner.get('cleanup', {}).get('survivors') == []
            and owner.get('additionalFilePinsBefore', {}).get(str(request_file)) == digest(request_file)
            and request['project'] in admitted and request['output'] == str(file.parent)
            and value.get('priorPreview') == request.get('previewFrom'),
            'Prior preview lacks its completed shared owner')
    require(value['packet'].get('schemaVersion') == 2 or request['project'] == project,
            'Prior preview belongs to another project')
    for clip in value['clips']:
        require(digest(Path(clip['path'])) == clip['sha256'], 'Prior preview media changed')
    return value


def preview_chain(file: Path, project: str) -> list[tuple[Path, dict]]:
    """Check ancestors too: unchanged units cannot survive a missing original preview."""
    identity = preview_identity(project)
    chain: list[tuple[Path, dict]] = []
    seen: set[Path] = set()
    while file:
        require(file.is_absolute() and file.resolve() == file and file not in seen
                and len(chain) < 64, 'Preview history is cyclic, noncanonical or exceeds 64 revisions')
        seen.add(file)
        value = preview_record(file, project, identity)
        chain.append((file, value))
        previous = Path(value['priorPreview']) if value.get('priorPreview') else None
        if previous:
            request = bound_json(file.parent / 'export-request.json')
            require(request.get('pins', {}).get(str(previous)) == digest(previous), 'Prior preview ancestor changed')
        file = previous
    for index, (_file, value) in enumerate(chain):
        previous = chain[index + 1][1]['packet'] if index + 1 < len(chain) else None
        request = bound_json(_file.parent / 'export-request.json')
        expected = [[row['startFrame'], row['endFrame']]
                    for row in request_preview_windows(request, value['packet'], previous)]
        require([row['absoluteFrameRange'] for row in value['clips']] == expected,
                'Prior preview chain omits required changed regions')
    return chain


def prior_preview(file: Path, project: str) -> dict:
    """Return the most recent record only after validating its complete evidence chain."""
    return preview_chain(file, project)[0][1]


def discover_preview(request: dict) -> Path | None:
    """Select the latest completed same-clip preview from bounded lineage history."""
    admitted, subject = preview_identity(request['project'])
    candidates = []
    for attempt in sorted(set(candidate_attempts(request)) | set(lineage_attempts(request))):
        file, delivery = attempt / 'motion-previews.json', attempt / 'delivery.json'
        if not delivery.exists():
            delivery = attempt / 'section-result.json'
        if not file.is_file() or not delivery.is_file():
            continue
        previous = bound_json(attempt / 'export-request.json')
        if previous.get('project') not in admitted:
            continue
        if not same_clip(bound_json(file).get('packet', {}), previous['project'], subject):
            continue  # Other packet schemas, clips or projects are incompatible, not corrupt.
        completed = bound_json(delivery).get('completedAt')
        if isinstance(completed, str):
            candidates.append((completed, str(file)))
    if not candidates:
        return None
    selected = Path(max(candidates)[1])
    prior_preview(selected, request['project'])
    return selected
