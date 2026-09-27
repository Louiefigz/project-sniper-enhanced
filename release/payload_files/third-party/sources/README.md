# Source of the ffmpeg that ships with Project Sniper

`install/deps/sniper-ffmpeg-8.0.3-1-osx-arm64.tar.xz` and
`install/deps/sniper-ffmpeg-8.0.3-1-osx-64.tar.xz` hold the architecture-matched `ffmpeg` and
`ffprobe` programs Sniper installs. Both are built from the two unmodified source archives here:

| File | Project | Licence |
|---|---|---|
| `ffmpeg-8.0.3.tar.xz` | FFmpeg 8.0.3, <https://ffmpeg.org> (release signed by the FFmpeg release key FCF986EA15E6E293A5644F10B4322F04D67658D8) | LGPL-2.1-or-later; this build is configured with `--enable-gpl --enable-version3`, so the programs are under the GNU GPL version 3 or later |
| `rubberband-4.0.0.tar.bz2` | Rubber Band Library 4.0.0, <https://breakfastquay.com/rubberband/> | GPL-2.0-or-later |

The complete build recipe is inside the archive under `share/sniper-ffmpeg/`:
`build_ffmpeg.sh` (the script used), `sniper-ffmpeg.json` (every configure option and pinned input),
`configuration.txt` (what the built program reports) and `BUILD.txt` (the exact conda-forge library
packages it was linked against, which the installer downloads from conda-forge). The GNU GPL text is
`share/sniper-ffmpeg/COPYING.GPLv3`.

You may copy, change and redistribute these programs under the GPL. Doing so does not affect your
licence to Project Sniper itself, which runs them as separate programs.
