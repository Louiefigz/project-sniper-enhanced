#!/bin/bash
# Build Sniper's ffmpeg and ffprobe for the private tool runtime (maintainer only).
#
#   release/runtime_deps/build_ffmpeg.sh          then: python -m release.runtime_tools pin-ffmpeg
#
# Why Sniper builds ffmpeg itself: the renderer needs the zscale (libzimg) and rubberband
# (librubberband) filters, and no trusted, pinned macOS arm64 build carries both.
# Every input is pinned in sniper-ffmpeg.json: the FFmpeg release tarball (its signature is
# checked against the FFmpeg release key), the rubberband release tarball, the configure
# options, and — from release/payload_files/install/deps/osx-arm64.lock — the exact
# conda-forge libraries a buyer installs, which this build links. rubberband is linked in
# statically; every other library through @rpath, and the only run path is
# @loader_path/../lib, so the binaries work wherever the runtime lives.
#
# Output (release/runtime_deps/dist/, not committed):
#   <artifact>.tar.xz   bin/ffmpeg, bin/ffprobe, share/sniper-ffmpeg/ (build record, licence)
#   sources/            the two source tarballs, shipped in the package as its GPL source
# Needs Apple's command-line tools (clang, install_name_tool, codesign) — on the maintainer's
# Mac only; buyers never compile anything.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT="$(cd "$HERE/../.." && pwd -P)"
PIN="$HERE/sniper-ffmpeg.json"
LOCK="$ROOT/release/payload_files/install/deps/osx-arm64.lock"
DIST="$HERE/dist"
pin() { /usr/bin/python3 -c 'import json,sys; v=json.load(open(sys.argv[1]))
for k in sys.argv[2].split("."): v=v[k]
print(" ".join(v) if isinstance(v,list) else v)' "$PIN" "$1"; }
sha() { /usr/bin/shasum -a 256 "$1" | awk '{print $1}'; }
say() { printf '%s\n' "$*"; }
die() { printf 'build_ffmpeg: %s\n' "$*" >&2; exit 1; }

WORK="$(pin work_dir)"; VERSION="$(pin version)"; ARTIFACT="$(pin artifact.file)"
MM="$DIST/tools/micromamba-2.9.0/bin/micromamba"
GPG="$(PATH="/opt/homebrew/bin:/usr/local/bin:$PATH" command -v gpg || true)"   # found before PATH is narrowed
[ -x "$MM" ] || die "run python -m release.runtime_tools solve first (it fetches the pinned micromamba)"
case "$WORK" in /private/tmp/*) ;; *) die "work_dir must stay the neutral /private/tmp path the pin records" ;; esac

fetch_sources() {
  local name file url want
  mkdir -p "$DIST/sources"
  for name in ffmpeg rubberband; do
    file="$(pin "sources.$name.file")"; url="$(pin "sources.$name.url")"; want="$(pin "sources.$name.sha256")"
    [ -f "$DIST/sources/$file" ] && [ "$(sha "$DIST/sources/$file")" = "$want" ] && continue
    curl -fsSL -o "$DIST/sources/$file.part" "$url"
    [ "$(sha "$DIST/sources/$file.part")" = "$want" ] || die "$file does not match its pinned SHA-256"
    mv "$DIST/sources/$file.part" "$DIST/sources/$file"
  done
}

verify_ffmpeg_signature() {
  local gnupg="$WORK/gnupg" key
  [ -n "$GPG" ] || die "gpg is needed to check the FFmpeg release signature"
  mkdir -p -m 700 "$gnupg"
  curl -fsSL "$(pin sources.ffmpeg.signing_key_url)" | GNUPGHOME="$gnupg" "$GPG" --quiet --import 2>/dev/null
  curl -fsSL -o "$WORK/ffmpeg.asc" "$(pin sources.ffmpeg.signature_url)"
  key="$(GNUPGHOME="$gnupg" "$GPG" --status-fd 1 --verify "$WORK/ffmpeg.asc" \
    "$DIST/sources/$(pin sources.ffmpeg.file)" 2>/dev/null | awk '/VALIDSIG/{print $3}')"
  [ "$key" = "$(pin sources.ffmpeg.signing_key)" ] || die "the FFmpeg tarball is not signed by the pinned release key"
  say "FFmpeg $VERSION signature: good ($key)"
}

# The runtime's conda rows as an explicit list micromamba installs and verifies itself.
explicit_list() {
  printf '@EXPLICIT\n'
  awk '$1 == "conda" { print $5 "#sha256:" $2 }' "$LOCK"
}

make_envs() {
  local mm_env=(env -i HOME="$WORK/mamba-home" PATH=/usr/bin:/bin MAMBA_ROOT_PREFIX="$WORK/mamba-root")
  explicit_list > "$WORK/explicit.txt"
  "${mm_env[@]}" "$MM" create --no-rc -y -q -p "$WORK/rt" --platform osx-arm64 --file "$WORK/explicit.txt"
  "${mm_env[@]}" "$MM" create --no-rc -y -q -p "$WORK/env" --platform osx-arm64 --file "$WORK/explicit.txt"
  # shellcheck disable=SC2046
  "${mm_env[@]}" "$MM" install --no-rc -y -q -p "$WORK/env" --override-channels -c conda-forge \
    --platform osx-arm64 --freeze-installed $(pin build_packages)
  ls "$WORK/env/conda-meta" | grep '\.json$' | sort > "$WORK/build-env-packages.txt"
}

build_rubberband() {
  tar -xjf "$DIST/sources/$(pin sources.rubberband.file)" -C "$WORK"
  ( cd "$WORK/rubberband-4.0.0" && meson setup build --prefix="$WORK/rb" $(pin rubberband_options) >/dev/null \
      && ninja -C build install >/dev/null )
}

build_ffmpeg() {
  local src="$WORK/ffmpeg-$VERSION" env="$WORK/env"
  tar -xJf "$DIST/sources/$(pin sources.ffmpeg.file)" -C "$WORK"
  ( cd "$src" && PKG_CONFIG_PATH="$WORK/rb/lib/pkgconfig:$env/lib/pkgconfig" PKG_CONFIG_LIBDIR="$WORK/rb/lib/pkgconfig:$env/lib/pkgconfig" \
    ./configure --prefix="$WORK/out" --cc=/usr/bin/clang --cxx=/usr/bin/clang++ --pkg-config="$env/bin/pkg-config" \
      --extra-cflags="-mmacosx-version-min=$(pin min_macos) -I$env/include" \
      --extra-ldflags="-mmacosx-version-min=$(pin min_macos) -L$env/lib -Wl,-rpath,$env/lib -Wl,-rpath,@loader_path/../lib -Wl,-headerpad_max_install_names" \
      --extra-libs=-lc++ $(pin configure) > "$WORK/configure.log" \
    && make -j"$(sysctl -n hw.ncpu)" > "$WORK/make.log" 2>&1 && make install > /dev/null 2>&1 ) \
    || die "the FFmpeg build failed; see $WORK/configure.log and $WORK/make.log"
}

# Drop the build-time run path, re-sign, and refuse anything that would not load from the runtime.
finish_binaries() {
  local tool lib bad=""
  for tool in ffmpeg ffprobe; do
    install_name_tool -delete_rpath "$WORK/env/lib" "$WORK/out/bin/$tool"
    codesign -s - -f "$WORK/out/bin/$tool" 2>/dev/null
    codesign -v "$WORK/out/bin/$tool" || die "$tool: invalid signature after re-signing"
    [ "$(otool -l "$WORK/out/bin/$tool" | awk '/LC_RPATH/{getline;getline;print $2}')" = "@loader_path/../lib" ] \
      || die "$tool: its only run path must be @loader_path/../lib"
    for lib in $(otool -L "$WORK/out/bin/$tool" | awk 'NR>1{print $1}'); do
      case "$lib" in
        /usr/lib/*|/System/Library/*) ;;
        @rpath/*) [ -e "$WORK/rt/lib/${lib#@rpath/}" ] || bad="$bad $tool:$lib" ;;
        *) bad="$bad $tool:$lib" ;;
      esac
    done
  done
  [ -z "$bad" ] || die "linked libraries the buyer's runtime does not have:$bad"
}

check_capabilities() {
  local bin="$WORK/rt/bin" have list kind missing=""
  cp "$WORK/out/bin/ffmpeg" "$WORK/out/bin/ffprobe" "$bin/"
  for kind in filters encoders decoders; do
    have="$("$bin/ffmpeg" -hide_banner "-$kind" 2>/dev/null | awk '{print $2}')"
    for list in $(pin "required_$kind"); do
      printf '%s\n' "$have" | grep -qx "$list" || missing="$missing $kind:$list"
    done
  done
  [ -z "$missing" ] || die "missing from the build:$missing"
  say "every required filter, encoder and decoder is present (checked inside the runtime-only env)"
}

package_artifact() {
  local stage="$WORK/artifact" doc
  rm -rf "$stage"; mkdir -p "$stage/bin" "$stage/share/sniper-ffmpeg"; doc="$stage/share/sniper-ffmpeg"
  cp "$WORK/out/bin/ffmpeg" "$WORK/out/bin/ffprobe" "$stage/bin/"
  cp "$WORK/ffmpeg-$VERSION/COPYING.GPLv3" "$doc/COPYING.GPLv3"
  # The recipe without its "artifact" field, which records this very file's hash afterwards.
  /usr/bin/python3 -c 'import json,sys; v=json.load(open(sys.argv[1])); v.pop("artifact")
print(json.dumps(v, indent=2))' "$PIN" > "$doc/sniper-ffmpeg.json"
  cp "$0" "$doc/build_ffmpeg.sh"
  "$WORK/rt/bin/ffmpeg" -hide_banner -buildconf > "$doc/configuration.txt" 2>/dev/null
  { say "Sniper ffmpeg $VERSION build $(pin build): FFmpeg $VERSION + rubberband 4.0.0 (static),"
    say "linked against the conda-forge packages of the runtime lock (the SHA-256 of its conda rows:"
    say "  $(awk '$1 == "conda"' "$LOCK" | /usr/bin/shasum -a 256 | awk '{print $1}'))."
    say "Build environment packages:"; sed 's/^/  /' "$WORK/build-env-packages.txt"
    say "Compiler: $(/usr/bin/clang --version | head -1)"; } > "$doc/BUILD.txt"
  find "$stage" -exec touch -h -t 202001010000 {} +
  ( cd "$stage" && find bin share -type f | LC_ALL=C sort > "$WORK/files.txt" \
    && COPYFILE_DISABLE=1 tar --no-mac-metadata --no-xattrs --no-acls --uid 0 --gid 0 --uname root --gname wheel \
         -cJf "$DIST/$ARTIFACT" -T "$WORK/files.txt" )
  say "$DIST/$ARTIFACT  $(sha "$DIST/$ARTIFACT")  $(stat -f %z "$DIST/$ARTIFACT") bytes"
}

export PATH="$WORK/env/bin:/usr/bin:/bin:/usr/sbin:/sbin" MACOSX_DEPLOYMENT_TARGET="$(pin min_macos)"
export CC=/usr/bin/clang CXX=/usr/bin/clang++
rm -rf "$WORK"; mkdir -p "$WORK" "$DIST"
fetch_sources
verify_ffmpeg_signature
make_envs
build_rubberband
build_ffmpeg
finish_binaries
check_capabilities
package_artifact
