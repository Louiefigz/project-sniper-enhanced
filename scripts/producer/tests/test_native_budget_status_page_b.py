"""Status page edge cases (X210 fix round; the L-V review's probes adopted as tests): every string escaped, null
blocks print "unknown" and keep the declared note, the authority refused under any spelling, the marker compared
whole, inclusive refresh bounds, a link or an unreadable file at --out refused, unlisted labels refused, and the
dark and narrow layouts declared. Input: ``tests/fixtures/status_page_input.json`` (provisional shape, W3-D11).
"""
from __future__ import annotations

import json
import os
import re
import unittest
from pathlib import Path

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused
from _status_fixture import temporary_directory
from studio import native_budget_store
from studio.native_budget_status_page import (FOREIGN_FILE, INSIDE_AUTHORITY, MARKER, PageMeta, render_page,
                                              write_page)
from studio.native_budget_status_page_style import CSS, DECLARED_NOTE

FIXTURE = Path(__file__).resolve().parent / 'fixtures' / 'status_page_input.json'
UNKNOWN_CELLS = ''.join(f'<td data-label="{label}">unknown</td>'
                        for label in ('Input', 'Cached', 'Output', 'Reasoning'))
# (where, path of keys set to null, what the page must then show). "clip" is q1's coordination block.
NULL_CASES = (
    ('clip', ('review', 'playedListened', 'played'), 'Played: unknown; listened: none'),
    ('clip', ('review', 'playedListened'), 'Played: unknown; listened: unknown'),
    ('clip', ('review', 'editoriallyApproved'), 'Approved: unknown</li>'),
    ('clip', ('review',), 'Ready: unknown</li><li>Shown: unknown</li><li>Played: unknown; listened: unknown'),
    ('clip', ('clock',), 'Clock (unknown)</h3><div class="small">counted unknown of unknown, unknown left</div>'),
    ('clip', ('compact', 'findings'), 'Findings by owner</h3><p>unknown</p>'),
    ('clip', ('compact',), 'owner unknown · plan unknown · active unknown'),
    ('clip', ('tokensByRole', 'team', 'totals'), f'<tr class="team"><td>team</td>{UNKNOWN_CELLS}'),
    ('clip', ('tokensByRole', 'team'), ' Unknown because: unknown</p>'),
    ('clip', ('tokensByRole', 'roles'), f'<tr><td>each role</td>{UNKNOWN_CELLS}'),
    ('clip', ('tokensByRole',), 'Tokens by role</h3><p>unknown</p>'),
    ('clip', ('identityNote',), DECLARED_NOTE),
    ('production', ('coordination',), '<p class="line">coordination unknown</p>'),
    ('production', ('state',), '<h2>q1 <span class="state">unknown</span>'),
    ('run', ('director',), '<dt>Director</dt><dd>unknown (session unknown); last action at unknown; silent unknown'),
    ('run', ('governance', 'limitations'), '<dt>Limitations</dt><dd>unknown</dd>'),
    ('run', ('governance',), '<dt>Governance</dt><dd>unknown: unknown</dd>'),
    ('run', ('sessions',), '<dt>Sessions</dt><dd>unknown</dd>'),
    ('run', ('quarantined',), '<dt>Quarantined</dt><dd>unknown</dd>'),
    ('run', ('unresolved',), '<dt>Unresolved</dt><dd>unknown</dd>'),
    ('status', ('production', 'coordination'), '<dt>Governance</dt><dd>unknown: unknown</dd>'),
    ('status', ('slaMisses',), 'encoded: unknown; visible hand-off: none'),
)


def status() -> dict:
    """A fresh copy of the fixture status read."""
    return json.loads(FIXTURE.read_text())


def stamp(batch: str = 'batch-page-fixture', banner: str | None = None) -> PageMeta:
    """A snapshot page stamp, refreshed every 10 s."""
    return PageMeta(batch, 1_800_001_265.4, 10, 1265.4, False, banner)


ENUMS = {'basis', 'verdict'}   # closed vocabularies: an unlisted value is refused (review m5), so they stay valid


def hostile(value: object, counter: list[int]) -> object:
    """Every free-text string leaf replaced by a numbered hostile token."""
    if isinstance(value, str):
        counter[0] += 1
        return f'<i{counter[0]}>"\'&</script></style>-->'
    if isinstance(value, list):
        return [hostile(item, counter) for item in value]
    if not isinstance(value, dict):
        return value
    return {key: item if key in ENUMS else hostile(item, counter) for key, item in value.items()}


def null_at(read: dict, where: str, keys: tuple[str, ...]) -> dict:
    """The status with the value at ``keys`` (under q1's block, q1's production, the run block or the top) null."""
    production = read['clips']['q1']['production']
    node = {'clip': production['coordination'], 'production': production,
            'run': read['production']['coordination'], 'status': read}[where]
    for key in keys[:-1]:
        node = node[key]
    node[keys[-1]] = None
    return read


class EscapeTests(unittest.TestCase):
    """No status text reaches the page unescaped."""

    def test_every_string_leaf_and_printed_key_is_escaped(self) -> None:
        """Every string value, clip id, finding owner, role label, SLA name and stamp text is hostile: none survives."""
        read = status()
        read['production']['coordination']['director']['advice'] = 'advice text'   # null in the fixture
        counter = [0]
        read = hostile(read, counter)
        for index, row in enumerate(read['clips'].values()):
            block = row['production']['coordination']
            block['compact']['findings'] = {f'<own{index}>': f'<cnt{index}>'}
            block['tokensByRole']['roles'] = {f'<role{index}>': next(iter(block['tokensByRole']['roles'].values()))}
        read['clips'] = {f'<clip{index}>"': row for index, row in enumerate(read['clips'].values())}
        read['slaMisses'], read['production']['visibleSlaMisses'] = ['<sla1>'], ['<sla2>']
        page = render_page(read, stamp('<batch>', '<banner>'))
        self.assertGreater(counter[0], 100)
        self.assertEqual(re.findall(r'<(?:i\d+|own\d|cnt\d|role\d|clip\d|sla\d|batch|banner)>', page), [])
        self.assertEqual((page.count('<script>'), page.count('</script>'), page.count('</style>')), (1, 1, 1))


class NullBlockTests(unittest.TestCase):
    """A null block never crashes the page; its fields print "unknown"; the declared note always shows."""

    def test_null_blocks_print_unknown_and_keep_the_declared_note(self) -> None:
        """Each container of the status, set to null, renders "unknown" where it would have shown."""
        for where, keys, shown in NULL_CASES:
            with self.subTest(where=where, keys=keys):
                page = render_page(null_at(status(), where, keys), stamp())
                self.assertIn(shown, page)
                card = page.split('<h2>q1 ')[1].split('</article>')[0]
                self.assertIn(f'<p class="note">{DECLARED_NOTE}</p>', card)

    def test_an_unknown_name_in_a_list_prints_unknown(self) -> None:
        """A null SLA name or session row prints "unknown" in place; the rest still prints."""
        read = status()
        read['slaMisses'] = [None, 'q1']
        read['production']['coordination']['sessions'].append(None)
        page = render_page(read, stamp())
        self.assertIn('encoded: unknown, q1;', page)
        self.assertIn('<li>unknown (unknown): unknown/unknown slots, unknown; host thread unknown; slots from', page)

    def test_an_unlisted_basis_or_verdict_is_a_shape_error(self) -> None:
        """An unknown playback basis or verdict is refused, never printed raw without its qualifier (review m5)."""
        for keys, value in ((('playedListened', 'played', 'basis'), 'watched'),
                            (('editoriallyApproved', 'verdict'), 'maybe')):
            read = status()
            node = read['clips']['q1']['production']['coordination']['review']
            for key in keys[:-1]:
                node = node[key]
            node[keys[-1]] = value
            with self.subTest(value=value), self.assertRaises(KeyError):
                render_page(read, stamp())


class AuthorityPathTests(unittest.TestCase):
    """The budget authority is refused under any spelling (X210 MAJOR-1): folder identity, not text."""

    def setUp(self) -> None:
        """The private authority root with its batches folder, and one rendered page."""
        self.root = native_budget_store.default_root()
        (self.root / 'batches').mkdir(parents=True, exist_ok=True)
        self.page = render_page(status(), stamp())

    def refused(self, target: Path) -> str:
        """write_page's refusal for ``target``; nothing may appear under the authority."""
        with self.assertRaises(ValueError) as caught:
            write_page(target, self.page)
        self.assertEqual(sorted(path.name for path in self.root.rglob('*')), ['batches'])
        return str(caught.exception)

    def test_a_case_variant_of_the_authority_is_refused(self) -> None:
        """A case variant of the root, or of an ancestor above it, names the same folder on this volume."""
        variants = (self.root.parent / self.root.name.swapcase() / 'status.html',
                    self.root.parent / self.root.name.swapcase() / 'BATCHES' / 'status.html',
                    self.root.parent.parent / self.root.parent.name.swapcase() / self.root.name / 'status.html')
        for target in variants:
            with self.subTest(target=target):
                same = target.parent.is_dir() and os.path.samefile(target.parent, self.root) \
                    or target.parent.is_dir() and os.path.samefile(target.parent.parent, self.root)
                expected = INSIDE_AUTHORITY if same else 'status-page --out is an absolute path in an existing folder'
                self.assertEqual(self.refused(target), expected)

    def test_a_link_at_out_into_the_authority_is_refused(self) -> None:
        """A link outside the authority whose target is inside it is refused as inside; its target is not made."""
        link = temporary_directory(self) / 'status.html'
        link.symlink_to(self.root / 'status.html')
        self.assertEqual(self.refused(link), INSIDE_AUTHORITY)

    def test_the_data_volume_firmlink_is_refused(self) -> None:
        """/System/Volumes/Data/<resolved root>/batches/status.html is the authority's batches folder (macOS)."""
        data = Path('/System/Volumes/Data')
        alias = data / self.root.resolve().relative_to('/') / 'batches' / 'status.html'
        if not alias.parent.is_dir():
            self.skipTest('no Data-volume firmlink for this root on this host')
        self.assertEqual(self.refused(alias), INSIDE_AUTHORITY)


class OutPathTests(unittest.TestCase):
    """What may stand at --out: only a status page (the whole marker), never a link or an unreadable file."""

    def setUp(self) -> None:
        """A private folder and one rendered page."""
        self.directory = temporary_directory(self)
        self.page = render_page(status(), stamp())

    def test_a_file_sharing_only_the_marker_prefix_is_not_a_page(self) -> None:
        """An HTML comment, or another marker version, is not MARKER: refused, unchanged."""
        for name, text in (('comment.html', '<!-- notes -->\n<html></html>\n'),
                           ('older.html', '<!-- sniper-status-page v0 -->\n<html></html>\n')):
            target = self.directory / name
            target.write_text(text)
            with self.subTest(name=name), self.assertRaises(ValueError) as caught:
                write_page(target, self.page)
            self.assertEqual((str(caught.exception), target.read_text()), (FOREIGN_FILE, text))

    def test_a_dangling_link_at_out_is_refused(self) -> None:
        """A link whose target does not exist is not a page: refused; the link stays, its target is not created."""
        link = self.directory / 'status.html'
        link.symlink_to(self.directory / 'elsewhere.html')
        with self.assertRaises(ValueError) as caught:
            write_page(link, self.page)
        self.assertEqual((str(caught.exception), link.is_symlink(), (self.directory / 'elsewhere.html').exists()),
                         (FOREIGN_FILE, True, False))

    def test_an_unreadable_file_at_out_is_refused(self) -> None:
        """A file that cannot be read is not known to be a page: refused, left as it was."""
        target = self.directory / 'status.html'
        target.write_text(MARKER + '\nold page\n')
        target.chmod(0)
        self.addCleanup(target.chmod, 0o600)
        with self.assertRaises(ValueError) as caught:
            write_page(target, self.page)
        target.chmod(0o600)
        self.assertEqual((str(caught.exception), target.read_text()), (FOREIGN_FILE, MARKER + '\nold page\n'))

    def test_a_lone_surrogate_is_refused_and_leaves_nothing(self) -> None:
        """Text that cannot be UTF-8 raises UnicodeEncodeError (a ValueError) and leaves no temporary file."""
        read = status()
        read['clips']['q1']['production']['coordination']['nextAction'] = 'bad \udc80'
        with self.assertRaises(UnicodeEncodeError):
            write_page(self.directory / 'status.html', render_page(read, stamp()))
        self.assertEqual(os.listdir(self.directory), [])

    def test_stamp_bounds(self) -> None:
        """Refresh 5 and 300 are accepted (inclusive); a bool is not a number for the epoch or the elapsed time."""
        self.assertEqual([PageMeta('b', 1.0, refresh, 1.0, False, None).refresh_seconds for refresh in (5, 300)],
                         [5, 300])
        for epoch, elapsed in ((True, 1.0), (1.0, False)):
            with self.subTest(epoch=epoch, elapsed=elapsed), self.assertRaisesRegex(ValueError, 'finite numbers'):
                PageMeta('b', epoch, 10, elapsed, False, None)


class LayoutTests(unittest.TestCase):
    """The layout rules the V check measured, pinned in the CSS data."""

    def test_dark_and_narrow_layouts_are_declared(self) -> None:
        """Dark tokens under prefers-color-scheme: dark; the token table stacks below 480 px."""
        dark = CSS.split('@media (prefers-color-scheme: dark) {')[1].split('\n}\n')[0]
        narrow = CSS.split('@media (max-width: 480px) {')[1].split('\n}\n')[0]
        self.assertIn('--bg: #141413', dark)
        self.assertIn('thead { display: none; }', narrow)
        self.assertIn('td[data-label]::before { content: attr(data-label) ": "', narrow)


if __name__ == '__main__':
    unittest.main()
