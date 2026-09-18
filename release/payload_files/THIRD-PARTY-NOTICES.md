# Third-party notices

Project Sniper includes and installs third-party software. This file is part of the
licence: keeping it with the software is a condition of several of the licences below.

Everything listed as **installed** is fetched from its publisher by the installer and is
not redistributed in this archive. Everything listed as **included** is inside this
archive.

## Included in this archive

### HyperFrames catalog mirror — Apache License 2.0
`app/vendor/hyperframes-catalog/` is an unmodified read-only mirror of the composition
registry in <https://github.com/heygen-com/hyperframes>, which is licensed under the
Apache License, Version 2.0. The full licence text is in
`licenses/Apache-2.0-hyperframes.txt` (retrieved from that repository on 2026-09-17).
No files in the mirror have been modified. Provenance, including the mirror date and the
one registry item that failed to mirror, is recorded in
`app/vendor/hyperframes-catalog/hyperframes-catalog-lock.json`.

The mirror's media assets (sound effects, wallpapers, textures, fonts) are **not**
included, because they are not read by the software and their individual terms were not
verified.

### Starter music bed — original, no third-party rights
`app/assets/music/default-bed.mp3` is synthesized from sine tones and filtered noise by
`app/scripts/producer/audio/default_bed.py`, which regenerates it. It replaced an earlier
synthesized bed that failed the product's own hum check (a 111 Hz line). The current bed
passes that check; it has been measured, not yet listened to by a person. It is available
to an edit only when you turn music on; your own licensed track in a project's `music/`
folder works the same way.

### GSAP 3.14.2 core, SplitText and DrawSVGPlugin — GSAP Standard "No Charge" licence
`app/templates/motion/vendor/gsap/`. Copyright GreenSock. Subject to the terms at
<https://gsap.com/standard-license>. Since GSAP 3.13 the standard licence covers
commercial use of the whole toolkit including these plugins. Each file retains its
`@license` header; the verbatim upstream README is kept beside them as the record.
Full provenance: `app/templates/motion/PROVENANCE.md`.

### Inter 4.1 — SIL Open Font License 1.1
`app/assets/fonts/Inter-Regular.ttf`, `Inter-Bold.ttf`, and the Inter faces embedded in
`app/templates/motion/tokens.css`. Copyright The Inter Project Authors
(<https://github.com/rsms/inter>). Licence text: `licenses/SIL-OFL-1.1-Inter.txt`.

### ChunkFive Regular — SIL Open Font License 1.1
`app/assets/fonts/ChunkFive-Regular.otf`. Copyright 2009 Meredith Mandel, with Reserved
Font Name "Chunk"; The League of Moveable Type. Licence text:
`licenses/SIL-OFL-1.1-ChunkFive.txt` (also shipped at
`app/assets/fonts/ChunkFive-OFL.markdown`).

### Caveat Bold — SIL Open Font License 1.1
`app/assets/fonts/Caveat-700-latin.woff2`. Copyright Pablo Impallari. The same OFL 1.1
terms apply; see either OFL text in `licenses/`.

### RNNoise model "beguiling-drafter" (2018-08-30)
`app/scripts/producer/audio/models/bd.rnnn`, from
<https://github.com/GregorR/rnnoise-models>. The upstream README states that the models
are not creative work and are not subject to copyright; only that repository's `tools/`
directory carries a licence. The verbatim upstream README is kept alongside the model as
`README.upstream.md`, and the file's SHA-256 is recorded in the `PROVENANCE.md` beside it.

### Bricolage Grotesque, Archivo, IBM Plex Mono — SIL Open Font License 1.1
`app/src/app/fonts/`. The app's interface fonts, vendored from the npm packages
`@fontsource-variable/bricolage-grotesque@5.3.0`, `@fontsource-variable/archivo@5.3.0` and
`@fontsource/ibm-plex-mono@5.3.0` so the app builds without contacting Google Fonts. Licence
texts: `licenses/SIL-OFL-1.1-Bricolage-Grotesque.txt`, `licenses/SIL-OFL-1.1-Archivo.txt`,
`licenses/SIL-OFL-1.1-IBM-Plex-Mono.txt`.

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
| `hyperframes` CLI and SDK 0.8.31 | HeyGen | Apache-2.0 (`licenses/Apache-2.0-hyperframes.txt`) |
| `chrome-headless-shell` | The Chromium Authors, via Chrome for Testing | BSD-3-Clause and the Chromium licence set |
| `ggml-small.en.bin` speech model | whisper.cpp project | MIT |
| `@openai/codex` CLI | OpenAI | its own published terms |
| `@anthropic-ai/claude-code` CLI | Anthropic | its own published terms |
| `ffmpeg`, `whisper-cpp`, Node, Python | you install these yourself | their own licences |

## Not shipped

| Material | Why |
|---|---|
| Development study libraries built from other creators' videos | Replaced by Sniper's own libraries in `app/resources/director` and `app/resources/references`; no creator's footage, frames or names ship. |
