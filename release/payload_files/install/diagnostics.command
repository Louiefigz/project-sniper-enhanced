#!/bin/bash
# Project Sniper — write a support bundle you can send. Redacted by construction:
# it copies ONLY the doctor's report, the app log's last lines and the release id.
# It never copies your footage, transcripts, edit plans, logins or tokens.
. "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh" || exit 1
load_env
OUT="$HOME/Desktop/sniper-diagnostics-$(date -u '+%Y%m%dT%H%M%SZ')"
mkdir -p "$OUT"
cp "$PKG_ROOT/RELEASE.json" "$OUT/RELEASE.json"
{ sw_vers; echo "arch: $(uname -m)"; echo "node: $(node --version 2>/dev/null)"; } > "$OUT/machine.txt"
"$PKG_ROOT/install/doctor.command" > "$OUT/doctor.txt" 2>&1
# Keep only lines the app itself printed, and drop anything that looks like a
# key, token or bearer header before it is written.
if [ -f "$LOG_DIR/app.log" ]; then
  tail -400 "$LOG_DIR/app.log" \
    | sed -E 's/(sk-[A-Za-z0-9_-]+|Bearer [A-Za-z0-9._-]+|eyJ[A-Za-z0-9._-]{20,})/[redacted]/g' \
    > "$OUT/app-log-tail.txt"
fi
say "Support bundle written to:"
say "  $OUT"
say "It contains the check report, your macOS/Node versions and the last app log"
say "lines with anything key-shaped removed. Read it before you send it."
