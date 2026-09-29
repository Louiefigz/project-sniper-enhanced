"""Who a managed Studio view belongs to and who relies on it: launcher token, hand-off holds, user hold.

A registry record names ``owner``/``ownerToken`` only when a hand-off's own call launched the view.
Every hand-off relying on a view is one hold that names its token and the evidence files (its
O_EXCL intent file and its record) through which ``prune-holds`` verifies it later; a plain
unowned open that reuses a view adds one user hold, so no hand-off release ever stops a view the
user is using. An owned open never replaces a stale view unless its own tag launched it and no
other token or the user still holds it (``ViewOwnedElsewhere``). Holds are capped
(``MAX_HOLDS``); a full list is refused with the holders and the recovery command named. A
record written by 46a7420 (an owner tag without a token) reads as a legacy view that no token
release can stop.
"""
from __future__ import annotations

import dataclasses
import re
from datetime import datetime, timezone
from pathlib import Path

from studio.studio_server import StudioServerError

_OWNER = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}')
_TOKEN = re.compile(r'[0-9a-f]{32}')
MAX_HOLDS = 16
MAX_EVIDENCE = 2
RECOVERY = 'native_handoff.py prune-holds --project <project> --record <new file>'


@dataclasses.dataclass(frozen=True)
class ViewOwner:
    """One hand-off's claim on a view: its tag, its minted token and its evidence files (intent, record)."""

    tag: str
    token: str
    evidence: tuple[str, ...] = ()


class ViewOwnedElsewhere(StudioServerError):
    """An owned open met a stale view of its project that someone else launched or still holds."""


class HoldsFull(StudioServerError):
    """A view already carries ``MAX_HOLDS`` holds; recover lost ones with ``prune-holds``."""


def owner_tag(value: object) -> str:
    """A bounded label for who launched a view (batch, run or task); never a path or a command."""
    if not isinstance(value, str) or _OWNER.fullmatch(value) is None:
        raise StudioServerError('Studio view owner must be 1-128 letters, digits or . _ : @ - '
                                '(starting with a letter or digit)')
    return value


def _evidence_ok(paths: object) -> bool:
    """At most two absolute evidence paths."""
    return isinstance(paths, (list, tuple)) and len(paths) <= MAX_EVIDENCE \
        and all(isinstance(path, str) and Path(path).is_absolute() for path in paths)


def view_owner(value: object) -> ViewOwner | None:
    """Validate an owner claim; None is an unowned open (the user's or a plain command's)."""
    if value is None:
        return None
    if not isinstance(value, ViewOwner) or not isinstance(value.token, str) or _TOKEN.fullmatch(value.token) is None \
            or not _evidence_ok(value.evidence):
        raise StudioServerError('Studio view owner needs a tag, a 32-hex-digit hand-off token and its evidence paths')
    owner_tag(value.tag)
    return value


def hold_of(owner: ViewOwner) -> dict:
    """The hold a hand-off leaves on a view it launched or reuses."""
    return {'owner': owner.tag, 'token': owner.token, 'evidence': list(owner.evidence)}


def valid_hold(row: object) -> bool:
    """A hand-off hold (tag, token, evidence; 156d2be holds had no evidence) or the one user hold."""
    if type(row) is not dict:
        return False
    if set(row) == {'user', 'since'}:
        return row['user'] is True and isinstance(row['since'], str)
    if set(row) not in ({'owner', 'token'}, {'owner', 'token', 'evidence'}):
        return False
    return view_owner(ViewOwner(row['owner'], row['token'], tuple(row.get('evidence', ())))) is not None


def validate_ownership(value: dict) -> None:
    """Launcher fields and holds of one record; an owner without a token is a legacy (46a7420) record."""
    if 'ownerToken' in value:
        view_owner(ViewOwner(value.get('owner'), value['ownerToken']))
    elif 'owner' in value:
        owner_tag(value['owner'])
    holds = value.get('heldBy', [])
    if type(holds) is not list or len(holds) > MAX_HOLDS or not all(valid_hold(row) for row in holds):
        raise StudioServerError('Managed Studio record has malformed holds')


def owned_by(value: dict) -> dict:
    """The launcher's owner, token and first hold: present only when the launching call named an owner."""
    owner = view_owner(value.get('owner'))
    return {} if owner is None else {'owner': owner.tag, 'ownerToken': owner.token, 'heldBy': [hold_of(owner)]}


def holder(row: dict) -> str:
    """A hold's holder, as a person reads it."""
    return 'the user' if row.get('user') else f"{row['owner']} ({row['token'][:8]})"


def refuse_foreign(project: str, stale: dict, owner: ViewOwner) -> None:
    """Replace a stale view only when this tag launched it and no other token or the user holds it."""
    others = [holder(row) for row in stale.get('heldBy', []) if row.get('token') != owner.token]
    launcher = stale.get('owner')
    if launcher == owner.tag and not others:
        return
    names = ', '.join([f"launcher {launcher or 'the user (no owner)'}", *others])
    raise ViewOwnedElsewhere(f'STUDIO_VIEW_OWNED_ELSEWHERE: the {stale["state"]} view of {project} is launched or '
                             f'held by others ({names}); this hand-off stops nothing it did not start')


def with_hold(entry: dict, owner: ViewOwner | None) -> dict:
    """The entry with this open's hold added (a hand-off's token, or the one user hold); capped."""
    hold = hold_of(owner) if owner else {'user': True, 'since': datetime.now(timezone.utc).isoformat()}
    same = (lambda row: row.get('token') == owner.token) if owner else (lambda row: bool(row.get('user')))
    holds = [row for row in entry.get('heldBy', []) if not same(row)]
    if len(holds) >= MAX_HOLDS:
        raise HoldsFull(f"Studio view of {entry['project']} already has {MAX_HOLDS} holds "
                        f"({', '.join(holder(row) for row in holds)}); recover lost ones with {RECOVERY}")
    return dict(entry, heldBy=[*holds, hold])
