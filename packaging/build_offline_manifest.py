"""Record the exact bundled wheels and generate offline, hash-locked installs."""
from __future__ import annotations

import argparse
import email
import hashlib
import json
import re
import zipfile
from pathlib import Path

OCR_EXTRAS = {"ocrmypdf", "deprecation", "img2pdf", "pi-heif", "pikepdf", "pluggy", "rich", "pygments", "markdown-it-py", "mdurl"}


def normalized(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(vendor: Path) -> dict:
    wheels = {}
    for path in sorted((vendor / "wheels").glob("*.whl")):
        with zipfile.ZipFile(path) as archive:
            metadata = email.message_from_bytes(archive.read(next(n for n in archive.namelist() if n.endswith(".dist-info/METADATA"))))
        wheels[path.name] = {"name": metadata["Name"], "version": metadata["Version"], "sha256": digest(path), "bytes": path.stat().st_size}
    if not wheels:
        raise ValueError("No offline wheels were supplied")
    profiles = {}
    for profile in ("base", "full"):
        selected = {filename: item for filename, item in wheels.items() if profile == "full" or normalized(item["name"]) not in OCR_EXTRAS}
        versions = {}
        lines = ["# Exact local wheels. No package index or network download is used."]
        for filename, item in sorted(selected.items(), key=lambda pair: normalized(pair[1]["name"])):
            if item["name"] in versions:
                raise ValueError("Duplicate package in wheelhouse: " + item["name"])
            versions[item["name"]] = item["version"]
            lines.append(f"{item['name']}=={item['version']} --hash=sha256:{item['sha256']}")
        path = vendor / f"requirements-{profile}.lock"
        path.write_text("\n".join(lines) + "\n")
        profiles[profile] = {"requirements": path.name, "requirements_sha256": digest(path), "versions": versions, "wheels": list(selected)}
    result = {"format": 1, "application_version": "0.5.0", "python_version": "3.12.15", "platform": "macos-arm64", "profiles": profiles, "wheels": wheels}
    (vendor / "manifest.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("vendor", type=Path)
    args = parser.parse_args()
    print(json.dumps({"packages": len(build(args.vendor)["wheels"])}))
