#!/bin/bash
set -euo pipefail

if [[ -z "${MACOS_CERTIFICATE_P12_BASE64:-}" ]]; then
    echo "No Apple signing certificate configured; the build will be ad-hoc signed."
    exit 0
fi

CERTIFICATE_PATH="$RUNNER_TEMP/inquisitio-signing.p12"
KEYCHAIN_PATH="$RUNNER_TEMP/inquisitio-signing.keychain-db"
KEYCHAIN_PASSWORD="$(openssl rand -hex 24)"

echo "$MACOS_CERTIFICATE_P12_BASE64" | /usr/bin/base64 -D > "$CERTIFICATE_PATH"
security create-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"
security set-keychain-settings -lut 21600 "$KEYCHAIN_PATH"
security unlock-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"
security import "$CERTIFICATE_PATH" -P "$MACOS_CERTIFICATE_PASSWORD" -A -t cert -f pkcs12 -k "$KEYCHAIN_PATH"
security set-key-partition-list -S apple-tool:,apple: -k "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"
security list-keychain -d user -s "$KEYCHAIN_PATH"
