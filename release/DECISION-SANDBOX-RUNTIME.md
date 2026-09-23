# Decision needed: how the Mac package admits footage

Found 2026-09-18 while running the first real edit on a fresh install of rc3 (`evidence/69-dev-codex-exercise.md`).
Corrected after the independent review (`evidence/76-independent-review.md`).

## What the code requires today

Producer admits every media file with `admit_external_media` (`headless/external_media_probe.py`, called from
`ingest_admission.py`). The file is fully decoded inside a network-less, non-root Docker container built from one
approved image (`headless/render_image_approval.json`, image `sha256:0e88874d…`). `required_runtime()`
(`headless/container_policy.py`) has no native fallback. Without Docker and that exact image, ingest stops at
"SNIPER_DOCKER_PATH must be an absolute executable path", and no Producer edit can start.

The same runtime is required by:
- guided-opening graphics;
- reference, scene and supporting-media admission;
- the guided layout, grade/colour and caption observations;
- colour diagnostics.

It is **not** required for everything:
- Graphics renders run natively when `SNIPER_RENDER_IMAGE_ID` is unset (`graphics/graphics_render.py`). The
  sealed container render path is used only when an image is configured.
- Segmenter and Clipper don't admit media and don't use the container.

The installed doctor now reports this as `media admission sandbox` and fails it. `RELEASE.json`,
`PENDING-OWNER-DECISIONS.txt` and the first-edit page say it too.

This conflicts with two recorded rules: the Mac package is native with no mandatory Docker, and admission and
sandboxing controls must not be disabled. Both cannot hold with today's code, so this is your call.

Facts that shape the choice:
- **The approved image can't be rebuilt by buyers.** A fresh build of the same `Dockerfile.g2` produced different
  layers (`68-`, `69-`), so buyers would have to receive the exact image.
- **The approved image is out of date for rc3.** The rename changed two container scripts that the image
  contains: the layout observer now names `module-pipeline`, and the image still has the old teacher-named
  identifier. Any Docker route needs a newly built and approved image.
- **The image contains Ubuntu's ffmpeg 4.4.2 and Chromium.** Distributing it brings their licence duties,
  including a source offer for ffmpeg's GPL components.
- **The Docker route also needs files the package withholds today,** including `templates/motion/container/`,
  which `render_layout_transport.py` reads, and an install step that sets `SNIPER_DOCKER_PATH`, `SNIPER_DOCKER_SOCKET`,
  `SNIPER_RENDER_IMAGE_ID` and `SNIPER_RENDER_UID_GID`.
- **The probe is pinned to `linux/arm64`**, so the Docker route would exclude Intel Macs.
- **`required_runtime()` accepts any Docker-compatible engine on a user-owned socket**, so Colima or OrbStack
  could stand in for Docker Desktop.

## Options

**A. A Docker-compatible runtime becomes a buyer prerequisite** (Docker Desktop, Colima or OrbStack).
The installer checks for it, then loads a newly approved image. The image comes from a `docker save` archive
delivered beside the ZIP (about 1 GB unpacked) or by digest from a registry you control.
- Keeps every control as built.
- Needs the container inputs shipped, an install step for those four settings, image redistribution
  notices and a GPL source offer.
- Apple silicon only.
- Reverses the no-mandatory-Docker decision and adds a heavy install for non-technical buyers. Docker Desktop's
  free tier covers personal use and businesses under 250 staff and $10M revenue.

**B. A native macOS sandbox for admission and the observation stages** (recommended if the no-Docker promise
matters for selling). Run the same full-decode probe under a macOS sandbox profile: no network, read-only input,
writes only to a scratch folder, plus time limits. The repository already ships sandbox profiles for other
stages (`studio/web_capture.sb`, `studio/native_localhost_only.sb`).
- Keeps the native-Mac decision and the probe's stated properties. The container's kernel isolation is replaced
  by the macOS sandbox. macOS does not enforce memory rlimits the way Linux does, so a memory and process cap
  needs another mechanism, such as a supervising watchdog; that is unsolved.
- Large and security-sensitive. Admission receipts bind the image ID and its tool closure, so they gain a
  native-runtime identity, and every reader of those receipts changes. The hostile-ingress cohort (the P0
  adversarial-ingress lane) must be re-qualified natively and independently reviewed.

**C. A narrow first step toward B.** Admit only the buyer's own local files through the native sandboxed probe,
and keep web-sourced media off in the Mac package until B is qualified.
- The quickest route to a working native edit.
- The observation stages still need B or Docker.
- Needs your explicit acceptance that local files lose container isolation.

Not offered: switching admission off. Render has a non-production `--allow-legacy-unadmitted` flag for migrating
old manifests; it is not a buyer route and would disable a control.

## What stays blocked until this is decided
- Z3–Z6 for Producer edits (real edits, revisions, playback, Studio) on the package.
- A meaningful clean-Mac install (Z2).
- The outside-operator run (Z10).
