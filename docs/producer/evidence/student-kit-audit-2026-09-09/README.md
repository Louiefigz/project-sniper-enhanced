# Audit evidence

Source repository: [hyperframes-student-kit](https://github.com/nateherkai/hyperframes-student-kit/tree/b1afdb1dcbcad39dd27638ea699f132fe44ce6df).
Pinned commit: `b1afdb1dcbcad39dd27638ea699f132fe44ce6df`.
Audit date: September 9, 2026. Node: v23.10.0.

- `source-tree-inventory.json`: complete 1,023-file tree from `git ls-tree -rz HEAD`, with Git blob identities and whether source was checked out. The isolated checkout contains 828 text/source/provenance files, including SVG source and three differing mirror entry points. No binary footage, images, audio or font files were fetched for playback.
- `audit-inventory.json`: categorized counts, all 14 skills, 12 teaching-project text inventories, all 14 root helper scripts and aggregate card results.
- `card-source-inventory.csv`: all 406 registry entries. Each corresponding HTML was parsed with Python's `HTMLParser`; the first composition root's declared dimensions/duration, literal slots and external `src`/`href` references were recorded. Preview presence was checked against the complete Git tree, not just the partial checkout. Missing literal slots are a flag for source inspection, not proof of a missing runtime slot. Source SHA-256 and Git blob identity are retained. No card was admitted or individually rendered.
- `skill-mirror-comparison.json`: 91 of 94 resource pairs have identical Git blobs; three entry points match after replacing `.claude/skills/` with `.agents/skills/`.
- `upstream-tests.txt`: captured output of both reviewed test files. All 11 passed. These tests use text fixtures and dummy file bytes; no media rendering or external requests.
- `reproduce-validator-probes.mjs` and `validator-probe-results.json`: nine targeted calls to two inspected pure validators. Three control/error behaviors matched expectations; six invalid inputs were accepted. This is a counterexample set, not a statistical failure-rate estimate.
- `local-comparison-sources.json`: SHA-256 snapshots of selected local files used for comparison. They establish which bytes were reviewed in a concurrently changing checkout; they are not production approval receipts.

To repeat the validator probes with a separately prepared checkout at the pinned commit, run:

```bash
node reproduce-validator-probes.mjs /absolute/path/to/pinned-student-kit /private/tmp/student-kit-validator-probes.json
```

To repeat the upstream text-only tests, from that source checkout run:

```bash
node --test tests/editing.test.mjs tests/short-form.test.mjs
```

Do not run the kit's setup, installation, rendering or media smoke commands as part of this audit reproduction. The report makes no claim of current-runtime browser playback, visual quality, natural speech cuts, end-to-end edit speed or compatibility based on these tests. The production benchmark remains independent.
