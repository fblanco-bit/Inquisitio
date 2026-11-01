#!/bin/bash
# Double-click in Finder. Python and all launch dependencies are included.
set -Eeuo pipefail
umask 077

ROOT="$(cd "$(dirname "$0")" && pwd)"
VENDOR="$ROOT/vendor/macos-arm64"
LOG_DIR="$HOME/Library/Logs/Inquisitio"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/startup.log"
LOCK=""
STAGING=""

prepare_runtime_for_macos() {
  local runtime_root="$1"
  local candidate
  local signed=0

  # Finder propagates quarantine to files unpacked from a downloaded ZIP. The
  # runtime archive is checksum-verified before this function is called, and
  # only the private extracted copy is modified.
  if [ -x /usr/bin/xattr ]; then
    /usr/bin/xattr -dr com.apple.quarantine "$runtime_root" >> "$LOG" 2>&1 || true
  fi

  if [ ! -x /usr/bin/codesign ]; then
    printf 'The macOS code-signing tool is unavailable.\n' >> "$LOG"
    return 1
  fi

  # python-build-standalone uses linker-generated ad hoc signatures. Refresh
  # every native component locally so current macOS execution policy accepts
  # the interpreter and its extension modules outside an application bundle.
  while IFS= read -r -d '' candidate; do
    if /usr/bin/file -b "$candidate" | /usr/bin/grep -q '^Mach-O'; then
      /usr/bin/codesign --force --sign - "$candidate" >> "$LOG" 2>&1
      /usr/bin/codesign --verify --strict "$candidate" >> "$LOG" 2>&1
      ((signed+=1))
    fi
  done < <(/usr/bin/find "$runtime_root" -type f \( -name 'python3.12' -o -name '*.dylib' -o -name '*.so' \) -print0)

  if [ "$signed" -eq 0 ]; then
    printf 'The included runtime did not contain any signable Mac components.\n' >> "$LOG"
    return 1
  fi
  printf 'Prepared and verified %d included Mac runtime components.\n' "$signed" >> "$LOG"
}

cleanup() {
  if [ -n "$STAGING" ] && [ -d "$STAGING" ]; then rm -rf "$STAGING"; fi
  if [ -n "$LOCK" ]; then rm -f "$LOCK/pid"; rmdir "$LOCK" 2>/dev/null || true; fi
}
failed() {
  trap - ERR
  printf '\nInquisitio could not finish starting. Details: %s\n' "$LOG" | tee -a "$LOG"
  if [ -x /usr/bin/osascript ]; then
    /usr/bin/osascript - "$LOG" <<'APPLESCRIPT' || true
on run argv
  display alert "Inquisitio could not finish starting" message ("Please share this log so the package can be corrected: " & item 1 of argv) as critical
end run
APPLESCRIPT
  fi
  exit 1
}
trap cleanup EXIT
trap failed ERR
trap 'printf "\nInquisitio stopped.\n"; exit 0' INT

printf '\n=== Inquisitio 0.5.2 | %s ===\n' "$(date)" >> "$LOG"
printf 'Starting Inquisitio 0.5.2. First launch prepares its included runtime.\n'

if [ "$(uname -s)" != Darwin ]; then
  printf 'This launcher requires an Apple Silicon Mac.\n' | tee -a "$LOG"
  exit 1
fi
if [ "$(uname -m)" != arm64 ] && [ "$(/usr/sbin/sysctl -n hw.optional.arm64 2>/dev/null || true)" != 1 ]; then
  printf 'This package is for Apple Silicon Macs (M-series processors).\n' | tee -a "$LOG"
  failed
fi

read -r EXPECTED_HASH < "$VENDOR/runtime.sha256"
RUNTIME_PARENT="$HOME/Library/Application Support/Inquisitio/runtimes"
RUNTIME="$RUNTIME_PARENT/python312-arm64-${EXPECTED_HASH:0:16}"
PYTHON="$RUNTIME/python/bin/python3"
mkdir -p "$RUNTIME_PARENT"

if [ ! -x "$PYTHON" ] || ! "$PYTHON" -I -c 'import ssl, sqlite3, venv' >> "$LOG" 2>&1; then
  LOCK_PATH="$RUNTIME.installing"
  ACQUIRED=0
  for ((attempt=0; attempt<240; attempt++)); do
    if mkdir "$LOCK_PATH" 2>/dev/null; then
      LOCK="$LOCK_PATH"
      printf '%s\n' "$$" > "$LOCK/pid"
      ACQUIRED=1
      break
    fi
    if [ -f "$LOCK_PATH/pid" ]; then
      read -r OWNER < "$LOCK_PATH/pid" || OWNER=""
      if [[ "$OWNER" =~ ^[0-9]+$ ]] && ! kill -0 "$OWNER" 2>/dev/null; then
        rm -f "$LOCK_PATH/pid"
        rmdir "$LOCK_PATH" 2>/dev/null || true
      fi
    elif [ "$attempt" -gt 20 ]; then
      rmdir "$LOCK_PATH" 2>/dev/null || true
    fi
    sleep 0.25
  done
  if [ "$ACQUIRED" -ne 1 ]; then
    printf 'Another launch is still preparing the runtime.\n' >> "$LOG"
    failed
  fi
  if [ ! -x "$PYTHON" ] || ! "$PYTHON" -I -c 'import ssl, sqlite3, venv' >> "$LOG" 2>&1; then
    printf 'Preparing included Python; no download is needed.\n'
    ACTUAL_HASH="$(/usr/bin/shasum -a 256 "$VENDOR/python.tar.gz" | /usr/bin/awk '{print $1}')"
    if [ "$ACTUAL_HASH" != "$EXPECTED_HASH" ]; then
      printf 'The included Python archive failed its integrity check.\n' >> "$LOG"
      failed
    fi
    STAGING="$(mktemp -d "$RUNTIME_PARENT/.inquisitio-unpack.XXXXXX")"
    /usr/bin/tar -xzf "$VENDOR/python.tar.gz" -C "$STAGING" >> "$LOG" 2>&1
    prepare_runtime_for_macos "$STAGING/python"
    "$STAGING/python/bin/python3" -I -c 'import ssl, sqlite3, venv' >> "$LOG" 2>&1
    if [ -d "$RUNTIME" ]; then rm -rf "$RUNTIME"; fi
    mv "$STAGING" "$RUNTIME"
    STAGING=""
  fi
  rm -f "$LOCK/pid"
  rmdir "$LOCK"
  LOCK=""
fi

"$PYTHON" -I "$ROOT/packaging/launch_runtime.py" --root "$ROOT" --vendor "$VENDOR" "$@" 2>&1 | tee -a "$LOG"
