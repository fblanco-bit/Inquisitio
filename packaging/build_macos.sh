#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

python -m pip install --upgrade pip
python -m pip install -r requirements-build.txt
python tests/offline_harness.py
python -m PyInstaller --clean --noconfirm packaging/Inquisitio.spec

APP="$ROOT/dist/Inquisitio.app"
test -x "$APP/Contents/MacOS/Inquisitio"
if [[ -n "${MACOS_SIGNING_IDENTITY:-}" ]]; then
    codesign --force --deep --options runtime --timestamp --sign "$MACOS_SIGNING_IDENTITY" "$APP"
else
    codesign --force --deep --sign - "$APP"
fi
codesign --verify --deep --strict "$APP"

export INQUISITIO_DATA_DIR="$(mktemp -d)/cases"
"$APP/Contents/MacOS/Inquisitio" --no-browser --port 8876 &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT
for _ in {1..60}; do
    if curl --silent --fail http://127.0.0.1:8876/api/health >/dev/null; then
        break
    fi
    sleep 1
done
curl --silent --fail http://127.0.0.1:8876/api/health >/dev/null
kill "$SERVER_PID"
wait "$SERVER_PID" 2>/dev/null || true
trap - EXIT

ARCH="$(uname -m)"
mkdir -p artifacts
if [[ -n "${APPLE_ID:-}" && -n "${APPLE_TEAM_ID:-}" && -n "${APPLE_APP_PASSWORD:-}" ]]; then
    NOTARY_ARCHIVE="artifacts/Inquisitio-notarization.zip"
    ditto -c -k --sequesterRsrc --keepParent "$APP" "$NOTARY_ARCHIVE"
    xcrun notarytool submit "$NOTARY_ARCHIVE" \
        --apple-id "$APPLE_ID" \
        --team-id "$APPLE_TEAM_ID" \
        --password "$APPLE_APP_PASSWORD" \
        --wait
    xcrun stapler staple "$APP"
    rm "$NOTARY_ARCHIVE"
fi
ditto -c -k --sequesterRsrc --keepParent "$APP" "artifacts/Inquisitio-macOS-${ARCH}.zip"
echo "Built artifacts/Inquisitio-macOS-${ARCH}.zip"
