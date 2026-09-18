# Release notes

## 0.1.0-rc1 — release candidate, not for sale

First assembled package. Previously Project Sniper could only be set up by a developer
working in the source tree; there was no archive, no installer and no manual.

### New
- **A real installer.** `install/install.command` installs both Node dependency roots,
  a Python environment from a pinned list, the exact rendering browser, the speech model
  and the pinned provider CLIs — all inside the package's own `runtime/` folder. It is
  safe to run again and resumes where it stopped.
- **Pinned provider CLIs, installed locally.** This release admits exactly one version of
  the Codex CLI and one of the Claude CLI. Those exact versions are now installed inside
  the package with their own settings folder and their auto-updater disabled, so your own
  CLI installation and login are untouched and an update to it cannot break Sniper.
- **A checker that asks the product, not a script.** `install/doctor.command` calls the
  product's own resolvers to report which browser, ffmpeg, node, speech model and runtime
  a render would actually use, and reports optional features as available, gated or
  needing a key rather than advertising them.
- **A complete offline manual** at `START-HERE.html`, in ten pages, with no links to
  anything you have to log in to.
- **Redacted diagnostics**, safe cache cleanup that lists candidates and sizes first, and
  an uninstall that leaves your videos alone.

### Fixed
- **Python dependencies are now pinned.** `requirements.txt` pinned almost nothing, so two
  installs a month apart produced different package versions — including a major
  `anthropic` version jump. The installer now installs `install/requirements.lock.txt`.
- **The rendering browser is now supplied.** The product resolves
  `chrome-headless-shell` from a user cache and refuses to download one during a render.
  Previously that only worked on a machine that happened to have the right build cached.
  The installer provisions the exact pinned build and points the product at it.
- **The install path is validated.** A path containing `,` `'` `:` or `\` silently broke
  the `voice-rnn` audio cleanup preset. The installer now refuses such a path up front and
  explains why, and the checker re-checks it.

### Known limits in this candidate
- Not qualified for sale. No clean-Mac install test, no full-length or Short output
  qualification, no delivery test. `RELEASE.json` records this.
- Licence terms are a draft. See `PENDING-OWNER-DECISIONS.txt`.
- Teacher-named identifiers remain in the shipped source. See `PENDING-RENAME.txt`.
- No sample clip is included; no footage is cleared for redistribution.
- The music bed asset is withheld pending provenance and a listening check.
- `next build` still fetches three fonts from Google Fonts, so building the web UI
  offline fails. The installer does not build it, and the CLI route does not need it.
- The `separate` audio preset needs Demucs, which is not installed. The other three
  cleanup presets work.
