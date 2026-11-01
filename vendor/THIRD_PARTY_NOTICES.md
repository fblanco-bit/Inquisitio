# Included third-party components

The bundled CPython runtime is the unmodified install-only stripped distribution from Astral's python-build-standalone project. Its release URL and published SHA-256 digest are recorded in macos-arm64/runtime-provenance.json. CPython and bundled runtime dependency licenses are retained inside the original archive.

Python dependency wheels are retained unmodified. Each wheel contains its upstream package metadata and license files; installation preserves their distribution metadata and license material. Exact package names, versions and SHA-256 digests are recorded in macos-arm64/manifest.json and the two requirements lock files.

Sources: https://github.com/astral-sh/python-build-standalone and https://pypi.org/ . These references are provenance only; application launch does not access them.

The original project fonts and their license remain in assets/.
