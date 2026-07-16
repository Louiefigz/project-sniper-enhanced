# B-roll asset pool

The operator's ground-truth pool for R17 **receipt** cutaways (the pro cuts to
the real artifact — his channel page, his sites, his old clips — while the
speech audio continues underneath). The planner proposes
`{assetId: null, note: "receipt: <entity>"}` rows; this pool is what resolves
them. Doctrine: assess-pool-FIRST; **the vision catalog is the source of
truth — naming is NEVER load-bearing** (a file named `youtube.mp4` resolves
nothing until the brain has looked at it and tagged it `youtube`).

## Folder convention

```
broll/
  README.md            <- committed; everything else in here is git-ignored
  .frames/             <- machine-written review thumbnails (never committed)
  screen-recordings/   <- category = the immediate subfolder name
  archive-clips/
  <any-category>/      <- add folders freely; the name is only a coarse tag
```

Drop media files (video or stills) into a category subfolder. The catalog
lives in this folder as `broll_catalog.json` (path+mtime keyed, committed —
the tags/descriptions are versioned judgment; shared with `ingest_scan`).

## Workflow

1. **Drop files** into a category subfolder.
2. **Scan** — `.venv/bin/python3 scripts/producer/broll_pool.py scan broll`
   Probes new/changed files, assigns stable ids, extracts 3 representative
   frames (15%/50%/85%) into `.frames/`, and prints the UNCATALOGED table.
   Idempotent; editing a file resets it to uncataloged and re-extracts.
3. **Brain annotates** — a Claude vision pass LOOKS at each asset's frames,
   then writes what it saw:
   `broll_pool.py annotate broll <id> --tags "youtube,channel,screen-recording" --description "..."`
   Tags are lowercase single tokens — they are the resolver's only match
   currency. The tool never invents tags.
4. **Manifest** — `broll_pool.py manifest broll` emits the
   `manifest["broll"]` array (cataloged assets only) for a project's
   `asset_manifest.json`; `plan_lint` and `broll_insert` consume it as-is.
5. **Resolve receipts** — `broll_pool.py resolve broll <proposal.json>` fills
   `brollReceipts` assetIds by exact token match against tags. One hit
   resolves; zero or many stays `needsOperator` (no fuzzy fallbacks).
   Concept-stock rows are never auto-resolved.
