"""What the Short derivation does not derive (global entries) and the writer vocabulary it stops on (P3a S2, M-081).

Every ``plan_projection(plan, local)`` path outside ``PROJECTION_DERIVED`` (X201 F-3) and every other native-plan path
outside ``PLAN_DERIVED`` (X205 F-5) becomes a global ``key-<path>`` entry, except ``GENERATED_EXEMPT`` (X211(1)).
Row fields the projection drops (X211(2)) are digested too: an asset row whole but its location in ``key-assets``;
a catalog file row's in its region entry when the row is region-bound (``catalog_unprojected``), else in
``key-catalogFiles``. A top-level or canvas key outside the writer vocabulary, or a malformed binding or P2 field,
stops by name (W3-D8, X211 minor): a renamed field never passes as a new global key.
"""
from __future__ import annotations

from studio.native_short_regions import EXECUTABLE_PLAN, plan_projection
from studio.production.coordination_catalog import (
    CANVAS_KEYS, GENERATED_EXEMPT, LOCATION_KEYS, PLAN_DERIVED, PROJECTION_DERIVED, WRITER_KEYS,
)
from studio.production.plan_fields import check

PROJECTED_KEYS = (*EXECUTABLE_PLAN, 'assets', 'catalogFiles')        # read whole by plan_projection
# The row fields plan_projection keeps (native_short_regions.py:135-139); the rest are "dropped" (X211(2)).
PROJECTION_ROW_KEYS = {'assets': ('file', 'role', 'sha256'), 'catalogFiles': ('file', 'catalogId', 'sha256')}
BINDINGS = {'sharedEvidence': ('path', 'sha256', 'contentSha256', 'version'), 'preparedSources': ('path', 'sha256')}


def _list_of(value: object, kind: type) -> bool:
    """None, or a list whose every row is ``kind``."""
    return value is None or type(value) is list and all(type(row) is kind for row in value)


def vocabulary_problem(native_plan: dict) -> None:
    """Stop by name on a key outside the writer vocabulary, a malformed binding, or a malformed P2 field."""
    canvas = native_plan['canvas']
    unknown = sorted(set(native_plan) - set(WRITER_KEYS)) + sorted(f'canvas.{key}' for key in set(canvas) - set(CANVAS_KEYS))
    check(not unknown, 'derived', f'native plan keys {unknown[:8]} are not in the writer vocabulary of SHORT_DERIVATION; '
          'a renamed or new writer field needs its table row first (R7, W3-D8)')
    for key, keys in BINDINGS.items():
        value = native_plan.get(key)
        check(value is None or type(value) is dict and set(value) == set(keys), 'derived',
              f'binding {key} must be null or exactly {list(keys)}')
    check(_list_of(canvas.get('captionProtectedPhrases'), list), 'derived', 'P2 field canvas.captionProtectedPhrases is malformed')
    check(_list_of(native_plan.get('speakerPictureDecisions'), dict), 'derived', 'P2 field speakerPictureDecisions is malformed')


def _rest(value: dict, derived: tuple[str, ...], prefix: str) -> dict[str, object]:
    """Every path of ``value`` not derived: a whole key, or the uncovered sub-keys of a key a derived path runs through."""
    found: dict[str, object] = {}
    for key, item in value.items():
        path = f'{prefix}{key}'
        if path in derived:
            continue
        if isinstance(item, dict) and any(other.startswith(f'{path}.') for other in derived):
            found.update(_rest(item, derived, f'{path}.'))
            continue
        found[path] = item
    return found


def unprojected(row: dict, section: str) -> dict:
    """The fields ``plan_projection`` drops from one row, its location excepted."""
    kept = set(PROJECTION_ROW_KEYS[section]) | set(LOCATION_KEYS)
    return {key: value for key, value in row.items() if key not in kept}


def catalog_unprojected(native_plan: dict, local: set[str]) -> dict[str, list[dict]]:
    """Region file -> the dropped fields of its catalog rows (the region's own entry digests them)."""
    found: dict[str, list[dict]] = {}
    for row in native_plan.get('catalogFiles') or []:
        if row.get('file') in local:
            found.setdefault(row['file'], []).append(unprojected(row, 'catalogFiles'))
    return found


def unlisted(native_plan: dict, local: set[str]) -> dict[str, object]:
    """Every plan path the table does not derive, with its value (projection F-3, rest F-5, dropped fields X211(2))."""
    projection = plan_projection(native_plan, local)
    found = _rest(projection, PROJECTION_DERIVED, '')
    found['assets'] = [{key: value for key, value in row.items() if key not in LOCATION_KEYS}
                       for row in native_plan.get('assets') or []]
    found['catalogFiles'] = {'projected': projection['catalogFiles'],
                             'unprojected': [unprojected(row, 'catalogFiles') for row in native_plan.get('catalogFiles') or []
                                             if row.get('file') not in local]}
    rest = {key: value for key, value in native_plan.items() if key not in PROJECTED_KEYS and key not in GENERATED_EXEMPT}
    found.update({f'plan.{path}': value for path, value in _rest(rest, PLAN_DERIVED, '').items()})
    return found


def unlisted_keys(native_plan: dict) -> list[str]:
    """Paths of the native plan that SHORT_DERIVATION does not derive; each is a global ``key-<path>`` entry."""
    return sorted(unlisted(native_plan, set()))


def prepared_digest(native_plan: dict) -> str | None:
    """The prepared working media's identity (X211(1)): its sha256, the location left out; None without one."""
    return (native_plan.get('preparedSources') or {}).get('sha256')
