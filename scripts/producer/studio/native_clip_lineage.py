"""Verified logical clip lineage for native Short preview reuse; never an approval.

The TypeScript writer records ``lineage`` in PROJECT-MANIFEST.json: a random clip
identity for a new root, or the parent project's canonical path, manifest bytes
and projectHash for a rebuilt revision. This reader re-verifies every ancestor's
manifest bytes before discovery may consider that ancestor's preview attempts,
so a revision folder change keeps its reuse while another clip's media never
qualifies. Reuse itself still requires identical content dependency hashes.
"""
from __future__ import annotations

import re
from pathlib import Path

from cut_preview_io import bound_json, real_directory
from studio.native_runtime import digest as file_digest
from studio.native_stage_evidence import require

MAX_GENERATION = 64
CLIP = re.compile(r'[0-9a-f]{32}')
SHA = re.compile(r'[0-9a-f]{64}')
LINEAGE_KEYS = {'schemaVersion', 'clipId', 'generation', 'parent'}
PARENT_KEYS = {'path', 'projectHash', 'manifestSha256', 'clipId', 'generation'}


def _generation(value: object) -> int:
    """Bound one recorded generation without accepting booleans or floats."""
    require(type(value) is int and 0 <= value <= MAX_GENERATION, 'clip lineage generation is outside its bound')
    return value


def validate_lineage(value: object) -> dict:
    """Check the exact recorded shape; paths are verified only when an ancestor is used."""
    require(type(value) is dict and set(value) == LINEAGE_KEYS and value['schemaVersion'] == 1
            and isinstance(value['clipId'], str) and CLIP.fullmatch(value['clipId']) is not None,
            'clip lineage needs schema 1 and a 128-bit clip identity')
    generation, parent = _generation(value['generation']), value['parent']
    if parent is None:
        require(generation == 0, 'root clip lineage must be generation 0')
        return value
    require(type(parent) is dict and set(parent) == PARENT_KEYS and isinstance(parent['path'], str)
            and Path(parent['path']).is_absolute() and str(Path(parent['path'])) == parent['path']
            and all(isinstance(parent[key], str) and SHA.fullmatch(parent[key]) is not None
                    for key in ('projectHash', 'manifestSha256'))
            and parent['clipId'] == value['clipId'] and _generation(parent['generation']) + 1 == generation,
            'clip lineage parent is not a canonical same-clip predecessor')
    return value


def project_lineage(project: Path) -> dict | None:
    """Return the recorded lineage, or None for legacy and non-Short projects."""
    file = project / 'PROJECT-MANIFEST.json'
    if not file.is_file():
        return None
    lineage = bound_json(file).get('lineage')
    return None if lineage is None else validate_lineage(lineage)


def packet_subject(project: Path) -> dict:
    """Bind preview packets to a logical clip when recorded, else to the exact project path."""
    lineage = project_lineage(project)
    return {'clip': lineage['clipId']} if lineage else {'project': str(project)}


def verified_ancestors(project: Path) -> list[Path]:
    """Walk recorded parents nearest-first; a removed parent ends the verified chain."""
    lineage, ancestors = project_lineage(project), []
    while lineage and lineage['parent']:
        parent = lineage['parent']
        path = Path(parent['path'])
        if not path.exists() and not path.is_symlink():
            break  # Removed artifacts provide no reusable authority.
        real_directory(path)
        manifest_file = path / 'PROJECT-MANIFEST.json'
        require(file_digest(manifest_file) == parent['manifestSha256'], f'recorded parent manifest changed: {path}')
        manifest = bound_json(manifest_file)
        require(manifest.get('projectHash') == parent['projectHash'], f'recorded parent project changed: {path}')
        lineage = validate_lineage(manifest.get('lineage'))
        require(lineage['clipId'] == parent['clipId'] and lineage['generation'] == parent['generation'],
                f'recorded parent belongs to another clip lineage: {path}')
        require(path not in ancestors and path != project and len(ancestors) < MAX_GENERATION,
                'clip lineage is cyclic or exceeds its bound')
        ancestors.append(path)
    return ancestors


def lineage_projects(project: Path) -> list[str]:
    """The current project first, then each verified ancestor that may donate previews."""
    return [str(project), *map(str, verified_ancestors(project))]


def same_subject(packet: dict, other: dict) -> bool:
    """Compare the logical identity a preview was generated for, never its folder alone."""
    return packet.get('subject', {'project': packet.get('project')}) == other.get(
        'subject', {'project': other.get('project')})
