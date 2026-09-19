# Sniper's own tools — dependency record (maintainers)

Decided by the owner on 2026-09-18: buyers do not install Node, Python, ffmpeg/ffprobe,
whisper.cpp, tesseract or yt-dlp. Setup downloads and verifies Sniper's own copies. This file
records what was chosen, from where, how it is verified and installed, and what is still limited.
The buyer-facing summary is `release/payload_files/RELEASE-NOTES.md` and `manual/install.html`.

## What is installed, and from where

| Tool | Version | Source | Licence |
|---|---|---|---|
| Python | 3.14.4 (`python-3.14.4-h4c637c5_100_cp314`) | conda-forge | Python-2.0 |
| Node (with npm 11.19.0) | 24.21.0 LTS | conda-forge | MIT |
| whisper.cpp (`whisper-cli`, Metal) | 1.9.3 | conda-forge | MIT |
| tesseract (all language data) | 5.5.3 | conda-forge | Apache-2.0 |
| yt-dlp | 2026.08.19 | conda-forge (noarch) | Unlicense |
| git | 2.55.0 | conda-forge | GPL-2.0-only |
| ffmpeg + ffprobe | 8.0.3, **Sniper build 1** | built here from FFmpeg 8.0.3 + Rubber Band 4.0.0 | GPL-3.0-or-later as configured |
| micromamba (installs the rest) | 2.9.0 | conda-forge | BSD-3-Clause AND MIT AND OpenSSL |

Plus the libraries these need: 86 conda-forge packages in all, about 294 MB. The complete list, with
every package's exact build, licence, size and SHA-256, is the lock:
`release/payload_files/install/deps/osx-arm64.lock` (read by the bash installer) and its companion
`osx-arm64.json` (read by Python and the notices). Both are written by
`python -m release.runtime_tools solve` from `specs.txt`; nothing is resolved on a buyer's Mac.

**Why conda-forge.** It is the one widely used, open, reproducibly built distribution that has all six
tools for macOS on Apple silicon as relocatable, pinned, hash-published packages. micromamba installs
them without compiling anything and without a system package manager. Homebrew bottles were rejected:
they are built for `/opt/homebrew` and relocating them needs Apple's developer tools, which buyers lack.

**Why Sniper builds ffmpeg.** The renderer needs the `zscale` (libzimg) and `rubberband` (librubberband)
filters (colour transforms in native export; pitch-preserving dialogue retime). conda-forge's ffmpeg
has neither, and conda-forge has no arm64 rubberband. Martin Riedl's and osxexperts' static builds have
zimg but not rubberband (osxexperts also re-uses one download URL, so a pin would break). The build:
- `build_ffmpeg.sh`, pinned by `sniper-ffmpeg.json`: FFmpeg 8.0.3 (the latest bug-fix release of the 8.0
  line the pipeline was qualified on with Homebrew's 8.0), signature checked against the FFmpeg release
  key FCF986EA15E6E293A5644F10B4322F04D67658D8; Rubber Band 4.0.0 (SHA-256 matches Homebrew's recorded
  checksum), built statically with Apple's vDSP.
- Links the lock's own conda-forge libraries (libzimg, libx264, libass, freetype, fontconfig, harfbuzz,
  fribidi, lame, opus, dav1d, OpenSSL, libc++) through `@rpath`; its only run path is
  `@loader_path/../lib`. The script refuses any other run path, any library the runtime lacks, and any
  missing required filter, encoder or decoder (the lists are in the pin).
- Reproducible: two independent builds produced byte-identical archives. The archive
  (`sniper-ffmpeg-8.0.3-1-osx-arm64.tar.xz`, 14.5 MB) ships in the package under `install/deps/`; its
  complete corresponding source (the two unmodified tarballs) and the recipe ship under
  `third-party/sources/` and inside the archive (`share/sniper-ffmpeg/`).
- Rebuild after changing the pin or re-solving the lock:
  `release/runtime_deps/build_ffmpeg.sh && python -m release.runtime_tools pin-ffmpeg`.

## How it is installed (`install/lib/runtime_tools*.sh`)

1. **Before anything else, with only macOS's own tools** (bash, curl, tar, shasum/openssl, codesign,
   lockf): Sniper's Python does not exist yet, and the maintenance lock's helper runs on it.
2. Refuses up front, before downloading: an Intel Mac (`sysctl hw.optional.arm64`), a macOS older than
   the lock's `min-macos` (13.5), a home folder whose path has whitespace. The floor is the highest of
   the packages' `__osx` metadata, the pinned Python wheels (13; opencv) and what the installed binaries
   themselves say: `python -m release.runtime_tools measure <runtime folder>` reads the `LC_BUILD_VERSION`
   of all 452 Mach-O files and records it in `measured-min-macos.json`. Node 24.21.0's `bin/node` and
   `libnode` are built for 13.5 although its package declares `__osx >=11.0`; the build refuses a lock
   below its measured floor, or a measurement taken for other packages.
   Parts outside this lock, measured the same way on the qualification install: the app's npm
   packages need at most 13.3 (onnxruntime-node); pip picks the macOS 11/12 builds of numpy and scipy
   on an older Mac (the requirements lock pins those too); the pinned Codex CLI 0.144.1 also carries a
   zsh built for macOS 15, used only by its optional `shell_zsh_fork` feature — the Codex route has not
   been run on macOS 13.5–14.
3. Downloads every lock row with curl into `~/.project-sniper/pkgs/` — resumable (`-C -`), each file
   checked against its SHA-256 before use; a wrong file is deleted and reported; a partial one resumes.
   `SNIPER_TOOLS_BASE_URL` serves the same paths from a mirror (installer tests).
4. Extracts micromamba and checks its binary's SHA-256 too.
5. `micromamba create --offline --platform osx-arm64 --always-copy` from `file://` URLs with
   `#sha256:` — into `~/.project-sniper/runtimes/<first 16 hex of the lock's SHA-256>/`, with
   micromamba's HOME and root prefix inside `~/.project-sniper` (never `~/.conda`/`~/.mamba`).
   `--platform` matters: without it micromamba does not re-sign the binaries it relocates, and Apple
   silicon kills them (seen while qualifying; now tested).
6. Unpacks Sniper's ffmpeg archive after checking its SHA-256, **through a pipe**, so it does not
   inherit the download quarantine of a browser-downloaded ZIP (owner decision 2026-09-18; it is not
   notarized — PENDING-OWNER-DECISIONS item 7).
7. Checks every Mach-O signature, runs each tool (ffmpeg's required features, tesseract's English data,
   Python's ssl/sqlite3), writes a SHA-256 record of every file, then the completion marker.
8. Under the maintenance lock, every run re-verifies the whole folder (about 16,600 files in ~1.5 s) and
   reinstalls it from the checked downloads if anything changed. The doctor does the same check and
   confirms each tool PATH finds is inside the folder.

**Why the tools live in `~/.project-sniper` and not in the package folder.** Studio identifies its
preview server by a whitespace-free Node path, and a buyer's package folder may contain spaces.
`~/.project-sniper` is already Sniper's per-user folder (the app keeps `projects.json` and
`config.json` there). Installs of releases with the same lock share one folder; each registers under
`<folder>/.sniper-users/`; uninstall removes the folder only when no registered install still uses it.
Moving or copying a package folder does not touch the tools.

**What the app sees.** The settings' PATH is `runtime/bin` (links into the folder), the pinned CLIs,
the folder's `bin`, then macOS's own folders — never Homebrew or `/usr/local`. Every launcher resets its
own PATH to macOS's folders and clears PYTHONPATH/PYTHONHOME, NODE_OPTIONS/NODE_PATH, DYLD_*,
CONDA_*/MAMBA_*, FONTCONFIG_* and TESSDATA_PREFIX (a certificate bundle set for a company proxy is kept).

## Limits that remain

- **Not notarized.** Nothing in the package has a Developer ID signature (owner decision item 7).
- **Supply.** Setup needs conda.anaconda.org to keep serving these exact packages (conda-forge does not
  normally delete published builds). A mirror or a hosted copy is a later decision.
- **yt-dlp ages.** A pinned yt-dlp stops working with some sites as they change; the fix is a new
  release with a re-solved lock.
- **Size.** About 300 MB downloaded and 1.2 GB on disk for the tools (tesseract's language data is most
  of it).
- **Tested boundary.** Only this developer Mac on macOS 26 has run it; the Intel refusal cannot be
  exercised here; a clean-Mac install is still to be done.
