#!/bin/sh
set -eu

archive=/request/render-input.tar
copy=/scratch/render-input.tar
expected=${SNIPER_INPUT_SHA256:?SNIPER_INPUT_SHA256 is required}

case "$expected" in
  *[!0-9a-f]* | "")
    echo "invalid render input digest" >&2
    exit 64
    ;;
esac
if [ "${#expected}" -ne 64 ]; then
  echo "invalid render input digest length" >&2
  exit 64
fi

/usr/bin/timeout --signal=TERM --kill-after=5s 30s /usr/bin/cp -- "$archive" "$copy"
actual=$(/usr/bin/timeout --signal=TERM --kill-after=5s 30s \
  /usr/bin/sha256sum "$copy")
actual=${actual%% *}
if [ "$actual" != "$expected" ]; then
  echo "sealed render input digest mismatch" >&2
  exit 65
fi

/usr/bin/mkdir -p /scratch/project
/usr/bin/timeout --signal=TERM --kill-after=5s 30s \
  /usr/bin/tar --extract --file "$copy" --directory /scratch/project \
  --no-same-owner --no-same-permissions

cli=/opt/sniper-motion/node_modules/hyperframes/dist/cli.js
if [ -n "${SNIPER_LAYOUT_REQUEST:-}" ]; then
  cli=/opt/sniper-motion/container/layout_observer_launch.mjs
fi
set +e
/usr/bin/timeout --signal=TERM --kill-after=10s 600s \
  /usr/bin/node "$cli" "$@" \
  > /output/render.log 2>&1
render_status=$?
set -e
/usr/bin/printf '%s\n' "$render_status" > /output/status.tmp
/usr/bin/mv -- /output/status.tmp /output/status

# Keep tmpfs alive briefly for the host stream. --rm plus this bounded hold
# reconciles the container even if the controller itself is SIGKILLed.
trap 'exit 143' TERM INT
/usr/bin/sleep 180
