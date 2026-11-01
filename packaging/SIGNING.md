# Native Release Signing

Public releases should be signed so macOS Gatekeeper and Windows SmartScreen can
verify the publisher. The build workflow accepts these repository secrets.

## macOS

- `MACOS_CERTIFICATE_P12_BASE64`: base64-encoded Developer ID Application certificate and private key.
- `MACOS_CERTIFICATE_PASSWORD`: password protecting the P12 file.
- `MACOS_SIGNING_IDENTITY`: full Developer ID Application identity.
- `APPLE_ID`: Apple developer account email used for notarization.
- `APPLE_TEAM_ID`: Apple Developer team identifier.
- `APPLE_APP_PASSWORD`: app-specific password used by `notarytool`.

When all notarization values are present, the workflow submits the application
to Apple and staples the accepted ticket before creating the download ZIP.

## Windows

- `WINDOWS_CERTIFICATE_PFX_BASE64`: base64-encoded Authenticode signing certificate and private key.
- `WINDOWS_CERTIFICATE_PASSWORD`: password protecting the PFX file.

When these values are present, the workflow signs and timestamps the executable
before running its packaged health check and creating the download ZIP.

Never place certificate files, private keys, or passwords in the source archive.
