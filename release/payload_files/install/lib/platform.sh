#!/bin/bash
# Native target detection used before Sniper's private Python exists.

sniper_platform_from() { # system machine native-arm64
  [ "$1" = Darwin ] || return 1
  if [ "$2" = arm64 ] || [ "$3" = 1 ]; then
    SNIPER_RUNTIME_PLATFORM=osx-arm64
    SNIPER_BROWSER_PLATFORM=mac-arm64
    SNIPER_BROWSER_PREFIX=mac_arm
    return 0
  fi
  [ "$2" = x86_64 ] || return 1
  SNIPER_RUNTIME_PLATFORM=osx-64
  SNIPER_BROWSER_PLATFORM=mac-x64
  SNIPER_BROWSER_PREFIX=mac
}

detect_sniper_platform() {
  sniper_platform_from "$(uname -s)" "$(uname -m)" \
    "$(/usr/sbin/sysctl -in hw.optional.arm64 2>/dev/null || printf 0)"
}

detect_sniper_platform || {
  printf 'STOPPED: Project Sniper supports Apple-silicon and Intel Macs; this platform is not recognized.\n' >&2
  exit 1
}
export SNIPER_RUNTIME_PLATFORM SNIPER_BROWSER_PLATFORM SNIPER_BROWSER_PREFIX
