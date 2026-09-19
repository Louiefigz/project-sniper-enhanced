# Third-party notices

Project Sniper includes and installs third-party software. This file is part of the
licence: keeping it with the software is a condition of several of the licences below.

Everything listed as **installed** is fetched from its publisher by the installer and is
not redistributed in this archive. Everything listed as **included** is inside this
archive.

## Included in this archive

### HyperFrames — Apache License 2.0 (three parts)
HyperFrames (<https://github.com/heygen-com/hyperframes>) is Copyright 2026 HeyGen, Inc.
and licensed under the Apache License, Version 2.0. The full licence text is in
`licenses/Apache-2.0-hyperframes.txt` (retrieved from that repository on 2026-09-17).
HyperFrames publishes no NOTICE file (checked 2026-09-18), so there is no upstream NOTICE
text to reproduce. The software is provided "AS IS", without warranties or conditions of
any kind. Project Sniper's modifications are not endorsed by HeyGen, Inc.

1. **Catalog mirror, unmodified** — `app/vendor/hyperframes-catalog/`. A read-only copy
   of the HyperFrames registry item sources, written by the HyperFrames CLI 0.7.33 on
   2026-08-28; Project Sniper does not edit these files (not re-verified against upstream
   bytes for this release: the lock records counts, not hashes). This archive contains
   only the README, the index, the lock and the item **HTML sources**, which are the
   files the catalog search reads. The mirror's media and script files are **not
   included**: the `assets/` folder (sound effects, wallpapers, textures, fonts, icons),
   `compositions/assets/` (fonts and the HyperFrames logo), `compositions/lib/` (a
   script library) and the texture images in `compositions/components/`. Provenance,
   including the one registry item that failed to mirror, is in
   `app/vendor/hyperframes-catalog/hyperframes-catalog-lock.json`.
2. **Adapted HyperFrames runtime, modified by Project Sniper** —
   `app/scripts/producer/studio/runtime/patches.json` holds 34 byte patches whose text
   contains portions of five files of the installed `hyperframes` 0.8.31 npm package
   (`dist/cli.js`, `dist/hyperframe.runtime.iife.js`, `dist/hyperframe-runtime.js`,
   `dist/hyperframe.manifest.json`, and `dist/native-capture-library.mjs` derived from
   the patched `cli.js`). Project Sniper modified these files. On your computer,
   `native_runtime.py` applies the patches to a separate copy under
   `templates/motion/.sniper-native-runtime/`; the installed package itself is not
   changed. The modification notice for each file is
   `app/scripts/producer/studio/runtime/NOTICE`. It sits beside the patches, not inside
   the patched files, because every adapted file is hash-checked before use.
   `frame-source-transport.mjs` and `native-export-guard.mjs` in that folder are
   Project Sniper's own files.
3. **Seven ported compositions, modified by Project Sniper** —
   `app/templates/motion/compositions/` `chart-story`, `count-up`, `hw-callout-circle`,
   `hw-scribble-transition`, `line-swap`, `marker-highlight` and `ui-focus-zoom` are
   derived from HyperFrames catalog items. Each file's header names its upstream item,
   carries the copyright line and licence reference, and states what Project Sniper
   changed. No other composition is recorded as derived from third-party code.

### GSAP 3.14.2 core, SplitText and DrawSVGPlugin — GSAP Standard "No Charge" License
`app/templates/motion/vendor/gsap/`, unmodified. Copyright GreenSock, as stated in each
file's `@license` header. Licensed by Webflow under the GSAP Standard "No Charge" License
at <https://gsap.com/standard-license>. Since GSAP 3.13 that licence permits commercial use
of the whole toolkit, including these plugins, at no charge. It is subject to restrictions.
One of them forbids use in no-code visual animation tools that compete with Webflow's
visual animation building capabilities without Webflow's prior written consent. The
licence also forbids removing the files' proprietary notices. These files remain subject
to those terms. The verbatim upstream README is kept beside them. Full provenance:
`app/templates/motion/PROVENANCE.md`. Project Sniper copies `gsap.min.js` and
`SplitText.min.js` into the review projects it creates on your computer.

### Fonts — SIL Open Font License 1.1
Each font keeps its own copyright line; the full licence text is in the file named.
- **Inter 4.1** — `app/assets/fonts/Inter-Regular.ttf`, `Inter-Bold.ttf`, and the Inter
  faces embedded in `app/templates/motion/tokens.css`. Copyright 2016 The Inter Project
  Authors (<https://github.com/rsms/inter>). Licence: `licenses/SIL-OFL-1.1-Inter.txt`
  (also `app/assets/fonts/Inter-OFL.txt`).
- **Caveat 2.000** (latin subset) — `app/assets/fonts/Caveat-700-latin.woff2` and the face
  embedded in `tokens.css`. Copyright 2014 The Caveat Project Authors
  (<https://github.com/googlefonts/caveat>). Licence: `licenses/SIL-OFL-1.1-Caveat.txt`
  (also `app/assets/fonts/Caveat-OFL.txt`).
- **Bricolage Grotesque, Archivo, IBM Plex Mono** — `app/src/app/fonts/`, the app's
  interface fonts, vendored from the npm packages
  `@fontsource-variable/bricolage-grotesque@5.3.0`, `@fontsource-variable/archivo@5.3.0`
  and `@fontsource/ibm-plex-mono@5.3.0` so the app builds without contacting Google Fonts.
  Bricolage Grotesque and IBM Plex Mono (500 and 600) are also embedded unmodified in
  `tokens.css` as the motion graphics' display and label faces. Copyright 2022 The
  Bricolage Grotesque Project Authors; Copyright 2020 The Archivo Project Authors;
  Copyright 2017 IBM Corp. Licence texts: `licenses/SIL-OFL-1.1-Bricolage-Grotesque.txt`,
  `licenses/SIL-OFL-1.1-Archivo.txt`, `licenses/SIL-OFL-1.1-IBM-Plex-Mono.txt`.

### Lucide icons — ISC License
`app/templates/motion/icons/lucide/`: 55 glyphs from `lucide-static` 0.525.0, recoloured to
the Sniper accent; each file keeps its `@license` header. Copyright (c) for portions of
Lucide are held by Cole Bemis 2013-2022 as part of Feather (MIT); all other copyright
(c) for Lucide is held by Lucide Contributors 2022. Licence text:
`licenses/ISC-Lucide.txt` (the `lucide-static` 0.525.0 LICENSE file).

### Simple Icons brand marks — CC0 1.0, trademarks reserved by their owners
`app/templates/motion/icons/*.svg` (anthropic, claude, claude-color, codex, cursor, figma,
gemini, gemini-color, github, instagram, notion, openai, openai-color, perplexity, tiktok,
x, youtube): icon drawings from Simple Icons (<https://simpleicons.org>), dedicated to the
public domain under CC0 1.0 (`licenses/CC0-1.0-Simple-Icons.md`), recoloured. Sources and
fetch dates: `app/templates/motion/icons/manifest.json` and `icons/PROVENANCE.md`.
**Trademark caveat:** CC0 covers the drawings only. Every mark is a trademark of its
owner. Project Sniper uses a mark only to identify a product a speaker names. That use
implies no endorsement or affiliation. If you publish a video containing a mark, you are
responsible for that use, including the owner's brand guidelines. Simple Icons removed
the OpenAI mark in its version 16.0.0 (November 2025) after a public call to seek OpenAI's
agreement to keep it went unanswered. The `openai`, `codex` and `openai-color` files use
the drawing from Simple Icons 15.0.0 (path data identical, checked 2026-09-18).

### Starter music bed — original, no third-party rights
`app/assets/music/default-bed.mp3` is synthesized from sine tones and filtered noise by
`app/scripts/producer/audio/default_bed.py`, which regenerates it. It replaced an earlier
synthesized bed that failed the product's own hum check (a 111 Hz line). The current bed
passes that check; it has been measured, not yet listened to by a person. It is available
to an edit only when you turn music on; your own licensed track in a project's `music/`
folder works the same way.

### Sound effects and sample screenshot — original
`app/assets/sfx/` is synthesized by `app/scripts/producer/audio/sfx_library.py` (see the
`PROVENANCE.md` beside the files). `app/templates/motion/assets/sample-screen.png` is a
dashboard mock generated locally with Pillow, not any real product's interface.

### RNNoise model "beguiling-drafter" (2018-08-30)
`app/scripts/producer/audio/models/bd.rnnn`, from
<https://github.com/GregorR/rnnoise-models>. The upstream README states that the models
are not creative work and are not subject to copyright; only that repository's `tools/`
directory carries a licence. The verbatim upstream README is kept alongside the model as
`README.upstream.md`, and the file's SHA-256 is recorded in the `PROVENANCE.md` beside it.

### YuNet face-detection model — MIT License
`app/assets/models/face_detection_yunet_2023mar.onnx`, used for face-aware vertical framing.
Copyright (c) 2020 Shiqi Yu. From OpenCV Zoo (`models/face_detection_yunet/`), whose README
states that all files in that directory are MIT-licensed. The shipped file's SHA-256
(`8f2383e4…d2552fa4`, 232,589 bytes) matches the upstream Git LFS record for
`face_detection_yunet_2023mar.onnx` exactly (checked 2026-09-17). Licence text:
`licenses/MIT-YuNet-face-detection.txt`.

### Director library and reference library — original to Project Sniper
`app/resources/director/` and `app/resources/references/` were written for Project Sniper.
The reference frames are rendered from Project Sniper's own motion templates; each frame
records the composition, variables and time that produced it. No third-party footage,
screenshot, brand, likeness or creator name is used.

## Installed by the installer, not redistributed here

| Component | Publisher | Licence |
|---|---|---|
| Node dependencies of `app/` and `app/templates/motion/` | various, via npm | each package's own; `npm ci` installs them from the lockfiles |
| `hyperframes` CLI and SDK 0.8.31 | HeyGen | Apache-2.0 (`licenses/Apache-2.0-hyperframes.txt`). Its Studio web bundle contains its own copy of GSAP 3.15.0 under the GSAP Standard "No Charge" License. |
| `chrome-headless-shell` | The Chromium Authors, via Chrome for Testing | BSD-3-Clause and the Chromium licence set |
| `ggml-small.en.bin` speech model | whisper.cpp project | MIT |
| `@openai/codex` CLI | OpenAI | its own published terms |
| `@anthropic-ai/claude-code` CLI | Anthropic | its own published terms |
| Sniper's own tools: Python 3.14.4, Node 24.21.0, whisper.cpp 1.9.3, tesseract 5.5.3 (with its language data), yt-dlp 2026.08.19, git 2.55.0, micromamba 2.9.0, and the libraries they and Sniper's ffmpeg use (86 packages in all) | conda-forge, <https://conda-forge.org> | each package's own; the complete list with every licence is `install/deps/osx-arm64.json`. They are downloaded by the installer from conda.anaconda.org, not redistributed in this package. |

## Shipped in this package: Sniper's ffmpeg build

| Component | Publisher | Licence |
|---|---|---|
| `ffmpeg` and `ffprobe` 8.0.3 (`install/deps/sniper-ffmpeg-8.0.3-1-osx-arm64.tar.xz`), built by Project Sniper from unmodified FFmpeg 8.0.3 and Rubber Band Library 4.0.0 | the FFmpeg developers; Particular Programs Ltd (Rubber Band) | GNU GPL version 3 or later as configured (FFmpeg itself is LGPL-2.1-or-later; Rubber Band is GPL-2.0-or-later). The complete corresponding source and the build recipe are in `third-party/sources/` and inside the archive under `share/sniper-ffmpeg/`, with the GPL text. They run as separate programs and do not change the licence of Project Sniper's own code. |

## Not shipped

| Material | Why |
|---|---|
| Development reference libraries built from other creators' videos | Replaced by Sniper's own libraries in `app/resources/director` and `app/resources/references`; no creator's footage or frames ship. |
| HyperFrames catalog media, fonts, logo, texture images and script library | The catalog search reads only item HTML; these files' individual terms were not verified. |
| ChunkFive font | No longer used by any template. |
| create-next-app sample icons and logos in `public/` | Unused; the app's favicon is Project Sniper's own. |
| Development test screenshots (`scripts/producer/tests/.artifacts/`) | Not product. |

**Known exceptions, blocking sale:**
- Several shipped studies measure the owner's own footage against edits of the owner's
  videos by editors the owner hired, some case records name the owner, and a few
  failure-ledger lessons describe a client's video. The owner has to confirm these may ship
  (`PENDING-OWNER-DECISIONS.txt`, item 6). The saved styles and the editing doctrine that
  were built from other creators' videos or a teacher's material are rewritten as Sniper's
  own and no longer name creators.
- GSAP licence scope is not cleared. It is not yet confirmed that the GSAP Standard
  License allows shipping these files in a paid download, or that Project Sniper's editing
  surfaces fall outside its competing-tool restriction. A written answer from the publisher
  is needed before sale.
- Whether to keep shipping the OpenAI brand mark (see Simple Icons above) is an open owner
  decision.
