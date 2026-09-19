# Release notes

## 0.1.0-rc4 — release candidate, not for sale

### Sniper installs its own tools
- **Nothing to install first.** Setup downloads Sniper's own Python 3.14.4, Node 24.21.0,
  whisper.cpp 1.9.3, tesseract 5.5.3, yt-dlp 2026.08.19 and git 2.55.0 from conda-forge (about
  300 MB), checks every file against the SHA-256 recorded for this release, and installs them
  into `~/.project-sniper`. Homebrew, Xcode, Python and Node are no longer needed, and your own
  copies are never used or changed — even when they come first on your PATH.
- **Sniper's own ffmpeg 8.0.3.** The renderer needs the zscale and rubberband filters, which no
  ready-made Mac build carries, so Sniper builds ffmpeg from the unmodified FFmpeg and Rubber Band
  sources. It ships in `install/deps/` with its complete source in `third-party/sources/` (GPL).
  It is not yet signed with an Apple Developer ID.
- **Checked on every run.** The installer and the doctor re-check every file of the tools
  against what was installed and that each tool runs; a changed file is reinstalled from the
  checked downloads. An interrupted download resumes.
- **Apple silicon, macOS 13.5 or later.** That is what the tools' own binaries need (Sniper's Node
  is built for 13.5, though its package says 11); the release measures it from every installed
  binary. Setup stops before downloading anything on an Intel Mac or an older macOS. Only macOS 26
  has been tested so far.
- Folders of the same release share one copy of the tools; uninstalling the last one removes it.
- Setup now signs you in first, then offers the optional Deepgram key.

### Footage admission without Docker
- **Every video Producer edits is checked on your Mac, in a macOS sandbox.** Before a
  Producer edit (or a deep reference study) reads a file, Sniper copies it into the project and
  fully decodes it with Sniper's own ffmpeg inside a sandbox. That sandbox has no network, cannot write files, cannot
  start other programs, reads only that one file and the decoder's own libraries,
  and cannot see other processes. A memory and CPU watchdog stops a runaway decode.
  Docker is no longer needed.
- Not covered: Segmenter, Clipper and the quick measurements of a reference video read the
  file directly with Sniper's own ffmpeg and Whisper, outside that sandbox.
- `install/doctor.command` admits a generated sample on your Mac and confirms the
  sandbox refuses a network connection and another file's contents, and stops a
  decode above its memory limit.

### What leaves your Mac
- Segmenter and Clipper now use your Codex or Claude subscription, like Producer. The
  API-key route and the Anthropic SDK are gone.
- The visual review of a rendered edit sends still frames, with that reviewer's tools
  switched off. The provider CLI runs in a sandbox that hides your project folder
  except those frames.
- Two optional features bill your own keys: Text Review (your Anthropic key and an opt-in
  for each run) and Deepgram transcription (your Deepgram key and explicit approval for each
  run). Setup can save a Deepgram key, and saving it approves nothing.

### Guided setup
- Double-click `install/setup.command`. It installs Sniper and its own tools, signs in to
  your subscription, connects Deepgram (optional, hidden prompt), runs the doctor and opens
  the editor window.
- Signing in, signing out and the editor window use only Sniper's own Claude settings,
  never your personal `~/.claude` settings or CLAUDE.md files.

### Original material
- The three saved styles and the editing doctrine are rewritten as Sniper's own
  specifications:
  - styles: Restrained, Punch and Slideware;
  - doctrine: module cards, editcraft, short-form and reference-style rules.
  Rule IDs and behaviour are unchanged.
- The Director library (formats, anchors, openings, training pairs) and the reference
  library are original. Old saved Director records still read; a full cold check of
  them does not pass.
- The motion templates use Sniper's own palette and type.
- `THIRD-PARTY-NOTICES.md` lists what actually ships.
- The HyperFrames catalog's fonts, textures and media are no longer shipped.

## 0.1.0-rc4 (installer and configuration)

- **One provider everywhere.** `editor.command` refuses a provider other than the one
  the install uses, and passes the same model settings to the editor window as the app
  uses. Switch the whole install with `use-provider.command` (app stopped).
- **Settings stored literally.** `runtime/sniper.env` is data, never run as shell, so
  folder names with `$`, quotes, backticks or accents read back exactly. Only a comma,
  apostrophe, colon or backslash in the install folder is refused (audio-cleanup limit).
- **One Node.** The app, doctor, CLIs and renders all use Sniper's own Node, also when
  started from Finder. The build refuses a Node below the floor (22.13) derived from the
  dependencies.
- **Every download checked.** Python packages install with `--require-hashes`; the two
  CLIs from a reviewed lockfile with `npm ci`; the rendering browser against a SHA-256
  recorded at build time.
- **Reruns repair.** Each step re-verifies the files it produced; anything missing,
  partial or changed is redone without manual cleanup.
- **One thing at a time.** The installer, provider switch, cache cleaning and uninstall
  refuse to start while the app, an editor window, the doctor or a render is running, and
  say what is in use (a real lock).
- **Truthful uninstall.** A failed stop or sign-out stops the removal and says so; your
  settings and export-recovery history are kept.
- **Studio through `install/studio.command`**, with this install's settings.
- The doctor checks tesseract and yt-dlp (reference features) and runs a real media
  admission sample instead of checking for Docker.

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
- Not qualified for sale. See `PENDING-OWNER-DECISIONS.txt`.
- No sample clip is included.
- The `separate` audio preset needs Demucs, which is not installed.

## 0.1.0-rc2 and rc1
Superseded candidates; their archives and evidence are preserved unchanged.
