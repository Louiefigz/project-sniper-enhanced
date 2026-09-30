"""The generated status page (P3b-14, M-111 stage A): every output and review chip, escaped, unknown never zero,
nothing loaded from anywhere, STALE after 3 x refresh, written atomically and only over its own page outside the
budget authority, and read back by no engine code. Input: ``tests/fixtures/status_page_input.json``
(provisional shape, W3-D11). ``test_snapshot_writes_nothing`` and ``test_watch_stops_on_closed_batch`` are
M-111's stage B (they need M-110's ``status_snapshot``).
"""
from __future__ import annotations

import json
import os
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused
from _status_fixture import temporary_directory
from studio import native_budget_store
from studio.native_budget_status_page import (FOREIGN_FILE, INSIDE_AUTHORITY, MARKER, PageMeta, render_page,
                                              write_page)
from studio.native_budget_status_page_style import BANNERS

TESTS = Path(__file__).resolve().parent
REPOSITORY = TESTS.parents[2]
FIXTURE = TESTS / 'fixtures' / 'status_page_input.json'
EPOCH = 1_800_001_265.4
HOSTILE = '<script>alert(1)</script> & "q" \'s\''
ESCAPED = '&lt;script&gt;alert(1)&lt;/script&gt; &amp; &quot;q&quot; &#x27;s&#x27;'
CODE = {'.py', '.mjs', '.cjs', '.js', '.ts', '.tsx', '.sh'}
SKIPPED = {'node_modules', '.git', '__pycache__'}
# The only code that names the page module or its marker. M-111 stage B adds studio/production/coordination_cli.py
# (it registers status-page and writes pages; it never reads one).
PAGE_CODE = {'scripts/producer/studio/native_budget_status_page.py',
             'scripts/producer/tests/test_native_budget_status_page.py'}


def names_the_page(path: Path) -> bool:
    """Whether a code file names the page module or its marker (``sniper-status-page``)."""
    text = path.read_text(errors='replace')
    return 'native_budget_status_page' in text or MARKER.split()[1] in text


def status() -> dict:
    """A fresh copy of the fixture status read."""
    return json.loads(FIXTURE.read_text())


def stamp(watch: bool = False, banner: str | None = None, batch: str = 'batch-page-fixture') -> PageMeta:
    """The page stamp of the fixture snapshot, refreshed every 10 s."""
    return PageMeta(batch, EPOCH, 10, 1265.4, watch, banner)


class RenderTests(unittest.TestCase):
    """What the page shows and how."""

    def test_page_contains_every_output_and_review_chips(self) -> None:
        """One card per output, four review chips each, and the run header facts."""
        read = status()
        page = render_page(read, stamp())
        self.assertTrue(page.startswith(MARKER + '\n<!DOCTYPE html>'))
        self.assertEqual(page.count('<article class="card">'), len(read['clips']))
        for clip_id in read['clips']:
            self.assertIn(f'<h2>{clip_id} <span class="state">', page)
        chips = page.split('<ul class="chips">')[1:]
        self.assertEqual([chip.split('</ul>')[0].count('<li>') for chip in chips], [4, 4])
        for text in ('Ready: labeled review draft at 19:40', 'Shown: not shown', 'Approved: not yet',
                     'Played: player observed playing (not proof a person watched) at 20:00; listened: none',
                     'Ready: checked final at 18:40', 'Shown: shown at 19:10', 'Approved: approved at 20:10',
                     'Played: declared by the reviewer, not authenticated by declared:claude-code:',
                     'owner declared:claude-code:s-00000000000000b2:agent-a41f · plan v2 frozen',
                     'queue waiting-for-ai-slot #2 · counted 14:05 used / 25:55 left',
                     'counted 14:05 of 40:00, 25:55 left', 'excluded render wait 3:10 (+0:12 uncertain)',
                     'author 2, operator 1', '<td>412,300</td>', 'Identities are declared by the coordinator, not '
                     'authenticated.', '<dt>Governance</dt><dd>declared: in-conversation subagents were not probed',
                     'ended at 10:10 by takeover; host thread declared', 'open; host thread not declared',
                     'repair-q2-r1 (session s-00000000000000a1): its session was taken over',
                     'review-q2-r0 (session s-00000000000000a1): no listed end observation',
                     'active (session s-00000000000000b2); last action at 19:50; silent 1:15',
                     'encoded: none; visible hand-off: none', 'active · preparation · elapsed 21:05'):
            self.assertIn(text, page)

    def test_page_escapes_text(self) -> None:
        """Every status value and stamp text is escaped; the STALE script is the only script."""
        read = status()
        block = read['clips']['q1']['production']['coordination']
        block['nextAction'] = block['compact']['owner'] = block['identityNote'] = HOSTILE
        block['compact']['findings'] = {HOSTILE: 1}
        block['tokensByRole']['roles'] = {HOSTILE: block['tokensByRole']['roles']['author']}
        block['review']['ready']['label'] = HOSTILE
        run = read['production']['coordination']
        run['governance']['limitations'].append(HOSTILE)
        run['sessions'][0]['session'] = run['quarantined'][0]['reason'] = run['director']['state'] = HOSTILE
        read['batchId'] = read['clips']['q2']['production']['state'] = HOSTILE
        page = render_page(read, stamp(banner=HOSTILE, batch=HOSTILE))
        self.assertEqual(page.count('<script>'), 1)   # the STALE script only
        self.assertNotIn('alert(1)</script>', page)
        self.assertEqual(page.count(ESCAPED), 16)   # every injected field, each escaped

    def test_unknown_renders_unknown(self) -> None:
        """None prints "unknown" in the clock, the chips, the compact line and the token table."""
        read = status()
        block = read['clips']['q1']['production']['coordination']
        block['clock'].update(countedSeconds=None, uncertainSeconds=None)
        block['compact']['queue'] = block['nextAction'] = None
        block['review']['ready'] = block['review']['shown'] = None
        page = render_page(read, stamp())
        self.assertIn('counted unknown of unknown, 25:55 left</div><div class="bar counted" title="unknown">', page)
        self.assertIn('(+unknown uncertain)', page)
        self.assertIn('queue unknown ·', page)
        self.assertIn('Ready: unknown</li><li>Shown: unknown</li>', page)
        self.assertIn('<strong>Next:</strong> unknown', page)
        critic = '<tr><td>critic</td>' + '<td>unknown</td>' * 4 + '</tr>'
        self.assertIn(critic, page)
        self.assertIn('<tr class="team"><td>team</td>' + '<td>unknown</td>' * 4, page)
        self.assertIn('Unknown because: 1 host task(s) have no transcript record', page)
        self.assertIn('excluded render wait unknown (+unknown uncertain)', render_page(status(), stamp()))

    def test_footer_names_source_of_truth(self) -> None:
        """The footer names the snapshot time, the status command and that the page decides nothing."""
        utc = datetime.fromtimestamp(EPOCH, timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        self.assertIn(f'<footer>Snapshot of the budget authority at {utc} (batch elapsed 21:05), read without '
                      'writing. Source of truth: native_batch.py status --batch batch-page-fixture. This page stores '
                      'nothing and decides nothing.</footer>', render_page(status(), stamp()))

    def test_page_has_no_external_urls(self) -> None:
        """Nothing is loaded from anywhere; the meta refresh appears only in watch mode."""
        page = render_page(status(), stamp())
        self.assertNotIn('http', page)
        for token in ('src=', 'href=', 'url(', '@import', '<link', '//', 'fetch(', 'xmlhttprequest', 'import('):
            self.assertNotIn(token, page.lower())
        self.assertNotIn(str(Path.home()), page)
        watched = render_page(status(), stamp(watch=True))
        tag = '<meta http-equiv="refresh" content="10">'
        self.assertEqual(watched.count(tag), 1)
        self.assertNotIn('http', watched.replace(tag, ''))

    def test_stale_banner_script_present(self) -> None:
        """The hidden STALE banner and the script that shows it after 3 x refresh."""
        page = render_page(status(), stamp())
        self.assertIn('<body data-generated-epoch="1800001265.4" data-refresh-seconds="10">', page)
        self.assertIn('<div class="banner stale" id="stale" hidden>STALE: this page has not been regenerated for '
                      'more than 30 seconds', page)
        script = page.split('<script>')[1].split('</script>')[0]
        self.assertIn('Date.now() / 1000 - generated > 3 * refresh', script)
        self.assertIn('banner.hidden = false', script)
        self.assertIn('setInterval(check, 1000)', script)

    def test_final_banner_and_page_stamp(self) -> None:
        """A final banner is shown only when given; an unprintable stamp is refused."""
        closed = BANNERS['closed'].format(batch='batch-page-fixture')
        self.assertIn(f'<div class="banner final">{closed}</div>', render_page(status(), stamp(banner=closed)))
        self.assertNotIn('banner final', render_page(status(), stamp()))
        for refresh in (4, 301, True, 10.0):
            with self.subTest(refresh=refresh), self.assertRaisesRegex(ValueError, 'refresh_seconds'):
                PageMeta('b', EPOCH, refresh, 1.0, False, None)
        for epoch, elapsed in ((float('nan'), 1.0), (EPOCH, float('inf')), ('1', 1.0)):
            with self.subTest(epoch=epoch), self.assertRaisesRegex(ValueError, 'finite numbers'):
                PageMeta('b', epoch, 10, elapsed, False, None)


class WriteTests(unittest.TestCase):
    """write_page: atomic, outside the authority, only over its own page."""

    def setUp(self) -> None:
        """A private folder and one rendered page."""
        self.directory = temporary_directory(self)
        self.page = render_page(status(), stamp())

    def leftovers(self) -> list[str]:
        """Temporary files write_page left in the directory."""
        return sorted(name for name in os.listdir(self.directory) if name.startswith('.status-page-'))

    def test_write_refuses_foreign_file_and_authority_root(self) -> None:
        """A foreign file, a folder, the authority (also through a link) and bad inputs are refused."""
        foreign = self.directory / 'notes.html'
        foreign.write_text('<html>mine</html>')
        for target in (foreign, self.directory):
            with self.subTest(target=target), self.assertRaises(ValueError) as caught:
                write_page(target, self.page)
            self.assertEqual(str(caught.exception), FOREIGN_FILE)
        self.assertEqual(foreign.read_text(), '<html>mine</html>')
        root = native_budget_store.default_root()
        (root / 'batches').mkdir(parents=True, exist_ok=True)
        (self.directory / 'into-authority').symlink_to(root, target_is_directory=True)
        for target in (root / 'status.html', root / 'batches' / 'status.html',
                       self.directory / 'into-authority' / 'status.html'):
            with self.subTest(target=target), self.assertRaises(ValueError) as caught:
                write_page(target, self.page)
            self.assertEqual(str(caught.exception), INSIDE_AUTHORITY)
            self.assertFalse(target.exists())
        for target, text in ((Path('status.html'), self.page), (self.directory / 'missing' / 'status.html', self.page),
                             (self.directory / 'status.html', '<html>not a page</html>')):
            with self.subTest(target=target), self.assertRaises(ValueError):
                write_page(target, text)
        self.assertEqual(self.leftovers(), [])

    def test_write_replaces_an_existing_page(self) -> None:
        """An existing page is replaced whole, with no temporary file left."""
        target = self.directory / 'status.html'
        write_page(target, self.page)
        closed = render_page(status(), stamp(banner=BANNERS['closed'].format(batch='batch-page-fixture')))
        write_page(target, closed)
        self.assertEqual((target.read_text(), self.leftovers()), (closed, []))

    def test_write_is_atomic(self) -> None:
        """A failed fsync or replace leaves the previous page intact and no temporary file."""
        target = self.directory / 'status.html'
        write_page(target, self.page)
        newer = render_page(status(), stamp(watch=True))
        for name in ('replace', 'fsync'):
            failing = mock.patch(f'studio.native_budget_status_page.os.{name}', side_effect=OSError(28, 'disk full'))
            with self.subTest(failing=name), failing, self.assertRaises(OSError):
                write_page(target, newer)
            self.assertEqual((target.read_text(), self.leftovers()), (self.page, []))


class NoReaderTests(unittest.TestCase):
    """The page is never a second source of truth: no code but the writer names its module or its marker."""

    def test_no_engine_code_reads_status_pages(self) -> None:
        """Only the writer and this test name the page module or its marker."""
        code = [path for top in ('scripts', 'src') for path in (REPOSITORY / top).rglob('*')
                if path.suffix in CODE and not SKIPPED.intersection(path.parts) and path.is_file()]
        found = {path.relative_to(REPOSITORY).as_posix() for path in code if names_the_page(path)}
        self.assertEqual(found, PAGE_CODE)


if __name__ == '__main__':
    unittest.main()
