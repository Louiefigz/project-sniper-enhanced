# Release notes

## 0.1.0-rc3 — release candidate, not for sale

### Product changes
- **Neutral names.** Styles, paces, presets, compositions, lint profiles and every
  document now use neutral names (`restrained`, `punch`, `slideware`, `module-*`).
  Projects made with earlier development builds need converting by the maintainer; the
  conversion tool is not part of this package.
- **Original Director library** (`app/resources/director/`): the hook anchors, formats,
  reference openings and training pairs the Director uses. No other repository is read.
- **Original reference library** (`app/resources/references/`): worked examples of
  editing mechanisms with frames rendered from Sniper's own templates.
- **The app builds offline.** Interface fonts are vendored; `next build` no longer
  contacts Google Fonts.

### Installer
- Builds the app during install, so `start.command` has something to start.
- Each step records what it finished with and is redone when its inputs change or it
  never finished. The speech model is reused from an identical copy on the Mac, resumes
  an interrupted download, and fails the install on a checksum mismatch.
- The chosen subscription is recorded and used consistently by sign-in, the checker and
  the app. `sign-in.command`, `editor.command` and `use-provider.command` run the pinned
  CLIs with this package's own settings.
- `start.command` confirms it is serving this install's build; `stop.command` signals
  only a process it can prove is this install's app.
- Python 3.12 is the minimum (the locked numpy, scipy and PyWavelets need it).
- Finder-launched scripts now find Homebrew tools.

### Checker
- The editor-brain check uses the same admission code as a real edit, for the provider
  you chose. It no longer reports an API-key or signed-out CLI as ready.
- The speech check verifies the model's checksum and transcribes a spoken sentence.

### Diagnostics, cleanup, uninstall
- Diagnostics contain structured facts only, not app-log text, unless you ask for it.
- Cache cleanup refuses to run while a render is active.
- Uninstall signs out the logins made for Sniper before removing files.

### Known limits
- Not qualified for sale. See `PENDING-OWNER-DECISIONS.txt` and `RELEASE.json`.
- No sample clip is included.
- The `separate` audio preset needs Demucs, which is not installed.

## 0.1.0-rc2 and rc1
Superseded candidates; their archives and evidence are preserved unchanged.
