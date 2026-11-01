"""Start the local application using the private, bundled Python installation."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

VERSION = "0.5.2"
PROBE_MODULES = ("fitz", "pdfplumber", "pypdf", "docx", "reportlab", "dateutil", "rapidfuzz", "PIL", "pytesseract")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def select_profile(manifest: dict) -> str:
    # OCRmyPDF 16's pikepdf 10 wheel requires macOS 14. The base application
    # supports macOS 11+ and retains the existing local pytesseract fallback.
    if sys.platform == "darwin" and int(platform.mac_ver()[0].split(".")[0]) >= 14:
        return "full"
    return "base"


def profile_fingerprint(vendor: Path, manifest: dict, profile: str) -> str:
    item = manifest["profiles"][profile]
    expected = item["requirements_sha256"]
    if sha256(vendor / item["requirements"]) != expected:
        raise RuntimeError("The included dependency list failed its integrity check.")
    return expected


def verify_wheels(vendor: Path, manifest: dict, profile: str) -> None:
    for filename in manifest["profiles"][profile]["wheels"]:
        info = manifest["wheels"][filename]
        path = vendor / "wheels" / filename
        if not path.is_file() or path.stat().st_size != info["bytes"] or sha256(path) != info["sha256"]:
            raise RuntimeError(f"The included dependency {filename} is missing or damaged.")


def installed_matches(manifest: dict, profile: str) -> bool:
    for name, version in manifest["profiles"][profile]["versions"].items():
        try:
            if importlib.metadata.version(name) != version:
                return False
        except importlib.metadata.PackageNotFoundError:
            return False
    modules = PROBE_MODULES + (("ocrmypdf", "pikepdf") if profile == "full" else ())
    code = "import importlib; [importlib.import_module(m) for m in " + repr(modules) + "]"
    return subprocess.run([sys.executable, "-I", "-c", code], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


@contextlib.contextmanager
def setup_lock(path: Path):
    # The kernel releases this lock even if setup is interrupted or crashes.
    import fcntl
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def ensure_dependencies(vendor: Path, state_dir: Path) -> str:
    manifest = json.loads((vendor / "manifest.json").read_text())
    profile = select_profile(manifest)
    fingerprint = profile_fingerprint(vendor, manifest, profile)
    with setup_lock(state_dir / "dependency-setup.lock"):
        if installed_matches(manifest, profile):
            print("Included dependencies are ready.", flush=True)
            return profile
        verify_wheels(vendor, manifest, profile)
        print("Preparing included PDF and export tools. No downloads are needed.", flush=True)
        requirement_file = vendor / manifest["profiles"][profile]["requirements"]
        command = [
            sys.executable, "-I", "-m", "pip", "--isolated", "--disable-pip-version-check",
            "install", "--no-index", "--find-links", str(vendor / "wheels"),
            "--only-binary=:all:", "--require-hashes", "--no-input", "--no-warn-script-location",
            "--force-reinstall", "-r", str(requirement_file),
        ]
        # A failed/interrupted install is repaired from the same local wheels.
        # Never fall back to a network index or request a command from the user.
        for attempt in range(2):
            result = subprocess.run(command)
            if result.returncode == 0 and installed_matches(manifest, profile):
                (state_dir / "dependencies-ready.json").write_text(json.dumps({"profile": profile, "sha256": fingerprint}))
                return profile
            if not attempt:
                print("Repairing the included tools automatically…", flush=True)
        raise RuntimeError("The included dependency installation could not be completed. See the startup log.")


def health(port: int) -> dict:
    # Never route a localhost readiness request through a user's proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"http://127.0.0.1:{port}/api/health", timeout=0.4) as response:
            result = json.load(response)
            return result if isinstance(result, dict) else {}
    except (OSError, ValueError, urllib.error.URLError):
        return {}


def open_browser(url: str) -> None:
    if sys.platform == "darwin":
        subprocess.run(["/usr/bin/open", url], check=True)
    else:
        webbrowser.open(url)


def open_when_ready(port: int, *, browser: bool = True, timeout: float = 30) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = health(port)
        if result.get("service") == "Inquisitio" and result.get("version") == VERSION:
            if browser:
                open_browser(f"http://127.0.0.1:{port}")
            print(f"Inquisitio {VERSION} is ready at http://127.0.0.1:{port}", flush=True)
            return True
        time.sleep(0.1)
    return False


def serve(root: Path, *, port: int | None = None, browser: bool = True) -> int:
    # Give OCR subprocesses the same standard Homebrew paths as an interactive
    # shell, without requiring the user to edit their shell configuration.
    os.environ["PATH"] = os.pathsep.join((str(Path(sys.executable).parent), "/opt/homebrew/bin", "/usr/local/bin", os.environ.get("PATH", "/usr/bin:/bin")))
    sys.path.insert(0, str(root))
    from inquisitio.server import Handler, InquisitioServer

    ports = [port] if port is not None else list(range(8765, 8785))
    for candidate in ports:
        if candidate and (existing := health(candidate)).get("service") == "Inquisitio" and existing.get("version") == VERSION:
            print(f"Opening the running Inquisitio {VERSION} workspace.", flush=True)
            if browser:
                open_browser(f"http://127.0.0.1:{candidate}")
            return 0
        try:
            server = InquisitioServer(("127.0.0.1", candidate), Handler)
            break
        except OSError:
            continue
    else:
        raise RuntimeError("No local port is available for Inquisitio.")

    actual_port = server.server_address[1]
    ready = threading.Thread(target=open_when_ready, args=(actual_port,), kwargs={"browser": browser}, daemon=True)
    ready.start()
    print(f"Starting Inquisitio {VERSION}. Keep this window open while working.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Inquisitio stopped.", flush=True)
    finally:
        server.server_close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Double-click Inquisitio startup")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--vendor", type=Path)
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--port", type=int)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    vendor = (args.vendor or root / "vendor/macos-arm64").resolve()
    state = args.state_dir or Path.home() / "Library/Application Support/Inquisitio/launcher"
    os.umask(0o077)
    try:
        ensure_dependencies(vendor, state)
        if args.check:
            sys.path.insert(0, str(root))
            from inquisitio.server import FORMS
            from inquisitio.server import PRODUCTION_FORM
            assert len(FORMS["202"].items) == 81 and len(FORMS["207"].items) == 55 and len(PRODUCTION_FORM.items) == 13
            print(f"Inquisitio {VERSION}: PDF tools and Forms 202/205/207 are ready.", flush=True)
            return 0
        return serve(root, port=args.port, browser=not args.no_browser)
    except Exception as exc:
        print(f"STARTUP ERROR: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
