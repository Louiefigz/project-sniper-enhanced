"""Data for the generated status page (P3b-14): its inline CSS, its one inline script and its fixed texts.

No logic and no external reference: the page loads nothing (no fonts, images, scripts or style sheets from
anywhere), so the CSS uses system fonts and the script only reveals the STALE banner.
"""
from __future__ import annotations

CSS = """
:root { color-scheme: light dark; --bg: #f6f6f3; --fg: #1c1c1a; --muted: #5b5b55; --card: #ffffff;
  --line: #dcdcd5; --chip: #ecece7; --counted: #2d6cb0; --excluded: #b0841a; --stale-bg: #fff0bf;
  --stale-fg: #533c00; --final-bg: #e7eef8; --final-fg: #1d3553; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #141413; --fg: #ebebe6; --muted: #a4a49c; --card: #1e1e1c; --line: #33332f; --chip: #2a2a27;
    --counted: #6ea5e2; --excluded: #d8b04a; --stale-bg: #4a390a; --stale-fg: #ffe8a3; --final-bg: #1d2a3b;
    --final-fg: #d6e5f7; }
}
* { box-sizing: border-box; }
html, body { margin: 0; }
body { background: var(--bg); color: var(--fg); padding: 16px; overflow-wrap: anywhere;
  font: 15px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
.banner { max-width: 960px; margin: 0 auto 12px; padding: 10px 12px; border-radius: 6px; font-weight: 600; }
.banner[hidden] { display: none; }
.banner.stale { background: var(--stale-bg); color: var(--stale-fg); }
.banner.final { background: var(--final-bg); color: var(--final-fg); }
header.run, footer { max-width: 960px; margin: 0 auto 12px; }
h1 { font-size: 1.3rem; margin: 0 0 2px; }
h2 { font-size: 1.1rem; margin: 0 0 4px; }
h3 { font-size: .75rem; letter-spacing: .05em; text-transform: uppercase; color: var(--muted); margin: 12px 0 4px; }
.meta, .note, footer, .small { color: var(--muted); font-size: .86rem; }
dl.facts { display: grid; grid-template-columns: minmax(6.5em, max-content) minmax(0, 1fr); gap: 4px 12px;
  margin: 8px 0; }
dl.facts dt { color: var(--muted); }
dl.facts dd { margin: 0; min-width: 0; }
ul.plain { margin: 0; padding-left: 1.1em; }
main.outputs { max-width: 960px; margin: 0 auto 12px; display: grid; gap: 12px;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 420px), 1fr)); }
article.card { background: var(--card); border: 1px solid var(--line); border-radius: 8px; padding: 12px;
  min-width: 0; }
.state { font-size: .8rem; font-weight: 500; color: var(--muted); }
.line { margin: 0 0 8px; }
.bar { position: relative; height: 10px; background: var(--chip); border-radius: 5px; overflow: hidden;
  margin: 2px 0 6px; }
.bar > span { position: absolute; left: 0; top: 0; bottom: 0; }
.bar.counted > span { background: var(--counted); }
.bar.excluded > span { background: repeating-linear-gradient(45deg, var(--excluded) 0 4px, transparent 4px 7px); }
ul.chips { list-style: none; padding: 0; margin: 8px 0; display: flex; flex-wrap: wrap; gap: 6px; }
ul.chips li { background: var(--chip); border-radius: 12px; padding: 2px 10px; font-size: .84rem; min-width: 0; }
table { width: 100%; table-layout: fixed; border-collapse: collapse; font-size: .84rem;
  font-variant-numeric: tabular-nums; }
th, td { text-align: right; padding: 3px 4px; border-bottom: 1px solid var(--line); }
th { font-size: .72rem; font-weight: 600; color: var(--muted); }
th:first-child, td:first-child { text-align: left; width: 22%; }
tr.team td { font-weight: 600; }
@media (max-width: 480px) {
  thead { display: none; }
  table, tbody, td { display: block; }
  tr { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 12px; padding: 4px 0;
    border-bottom: 1px solid var(--line); }
  td, th:first-child, td:first-child { border: 0; padding: 1px 0; text-align: left; width: auto; }
  td:first-child { grid-column: 1 / -1; font-weight: 600; }
  td[data-label]::before { content: attr(data-label) ": "; color: var(--muted); }
}
"""

STALE_SCRIPT = """
(function () {
  var body = document.body;
  var banner = document.getElementById('stale');
  var generated = Number(body.getAttribute('data-generated-epoch'));
  var refresh = Number(body.getAttribute('data-refresh-seconds'));
  function check() {
    if (Date.now() / 1000 - generated > 3 * refresh) { banner.hidden = false; }
  }
  check();
  setInterval(check, 1000);
})();
"""

STALE_TEXT = ('STALE: this page has not been regenerated for more than {window} seconds (3 x the {refresh} s '
              'refresh), so the watcher has stopped or cannot read the batch. Run native_batch.py status --batch '
              '{batch} for the current state.')
FOOTER = ('Snapshot of the budget authority at {utc} (batch elapsed {elapsed}), read without writing. Source of '
          'truth: native_batch.py status --batch {batch}. This page stores nothing and decides nothing.')

# Final banners run_page (stage B, M-111) passes in PageMeta.banner, formatted there.
BANNERS = {
    'closed': 'Batch {batch} is closed. This is its last page.',
    'expired': 'This page is no longer updated: the watch reached its --max-minutes limit at {utc}.',
    'interrupted': 'Live updates stopped at {utc}.',
    'error': 'The budget authority could not be read at {utc}: {error}. Below is the last good snapshot, from {last}.',
}

PLAYED_BASIS = {'player-observed-playing': 'player observed playing (not proof a person watched)',
                'declared-by-reviewer': 'declared by the reviewer, not authenticated', 'none': 'none'}
VERDICTS = {'approved': 'approved', 'not-approved': 'not approved',
            'not-verifiable-after-close': 'not verifiable after close'}
TOKEN_COLUMNS = (('inputTokens', 'Input'), ('cachedInputTokens', 'Cached'), ('outputTokens', 'Output'),
                 ('reasoningTokens', 'Reasoning'))
COMPACT_FIELDS = (('owner', 'owner'), ('plan', 'plan'), ('active', 'active'), ('queue', 'queue'),
                  ('counted', 'counted'), ('excluded', 'excluded'))
