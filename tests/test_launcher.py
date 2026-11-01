from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("launch_runtime", ROOT / "packaging/launch_runtime.py")
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


def bundle(tmp_path):
    vendor = tmp_path / "offline files with spaces"
    (vendor / "wheels").mkdir(parents=True)
    wheel = vendor / "wheels/example.whl"
    wheel.write_bytes(b"complete local wheel")
    req = vendor / "requirements-base.lock"
    req.write_text("example==1 --hash=sha256:" + launcher.sha256(wheel) + "\n")
    profile = {"requirements": req.name, "requirements_sha256": launcher.sha256(req), "versions": {"example": "1"}, "wheels": [wheel.name]}
    manifest = {"profiles": {"base": profile}, "wheels": {wheel.name: {"bytes": wheel.stat().st_size, "sha256": launcher.sha256(wheel)}}}
    (vendor / "manifest.json").write_text(json.dumps(manifest))
    return vendor, manifest


def test_first_launch_installs_only_local_hash_checked_wheels(tmp_path):
    vendor, _ = bundle(tmp_path)
    with patch.object(launcher, "select_profile", return_value="base"), patch.object(launcher, "installed_matches", side_effect=[False, True]), patch.object(launcher.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run:
        launcher.ensure_dependencies(vendor, tmp_path / "state")
    command = run.call_args.args[0]
    assert "--no-index" in command and "--require-hashes" in command and "--isolated" in command
    assert command[command.index("--find-links") + 1] == str(vendor / "wheels")
    assert "--index-url" not in command


def test_second_launch_does_not_run_pip(tmp_path):
    vendor, _ = bundle(tmp_path)
    with patch.object(launcher, "select_profile", return_value="base"), patch.object(launcher, "installed_matches", return_value=True), patch.object(launcher.subprocess, "run") as run:
        assert launcher.ensure_dependencies(vendor, tmp_path / "state") == "base"
    run.assert_not_called()


def test_incomplete_install_is_repaired_without_user_commands(tmp_path):
    vendor, _ = bundle(tmp_path)
    with patch.object(launcher, "select_profile", return_value="base"), patch.object(launcher, "installed_matches", side_effect=[False, True]), patch.object(launcher.subprocess, "run", side_effect=[SimpleNamespace(returncode=1), SimpleNamespace(returncode=0)]) as run:
        launcher.ensure_dependencies(vendor, tmp_path / "state")
    assert run.call_count == 2
    assert run.call_args_list[0].args == run.call_args_list[1].args


def test_corrupt_wheel_is_detected_before_installation(tmp_path):
    vendor, manifest = bundle(tmp_path)
    (vendor / "wheels/example.whl").write_bytes(b"interrupted file")
    with patch.object(launcher, "select_profile", return_value="base"), patch.object(launcher, "installed_matches", return_value=False), patch.object(launcher.subprocess, "run") as run:
        with pytest.raises(RuntimeError, match="missing or damaged"):
            launcher.ensure_dependencies(vendor, tmp_path / "state")
    run.assert_not_called()


def test_damaged_lock_is_detected_even_when_dependencies_are_ready(tmp_path):
    vendor, _ = bundle(tmp_path)
    (vendor / "requirements-base.lock").write_text("changed")
    with patch.object(launcher, "select_profile", return_value="base"):
        with pytest.raises(RuntimeError, match="integrity check"):
            launcher.ensure_dependencies(vendor, tmp_path / "state")


def test_mac_11_through_13_can_start_without_mac_14_ocr_wheel():
    with patch.object(launcher.sys, "platform", "darwin"), patch.object(launcher.platform, "mac_ver", return_value=("12.7.6", (), "arm64")):
        assert launcher.select_profile({}) == "base"
    with patch.object(launcher.sys, "platform", "darwin"), patch.object(launcher.platform, "mac_ver", return_value=("14.7", (), "arm64")):
        assert launcher.select_profile({}) == "full"


def test_browser_waits_for_the_correct_live_version():
    with patch.object(launcher, "health", side_effect=[{}, {"service": "Inquisitio", "version": "0.4.2"}, {"service": "Inquisitio", "version": launcher.VERSION}]), patch.object(launcher, "open_browser") as browser, patch.object(launcher.time, "sleep"):
        assert launcher.open_when_ready(8766)
    browser.assert_called_once_with("http://127.0.0.1:8766")


def test_browser_never_opens_a_failed_startup():
    with patch.object(launcher, "health", return_value={}), patch.object(launcher, "open_browser") as browser:
        assert not launcher.open_when_ready(8766, timeout=0.01)
    browser.assert_not_called()


def test_busy_default_port_uses_another_port(tmp_path):
    import inquisitio.server as server_module
    from unittest.mock import MagicMock
    fake_server = MagicMock()
    fake_server.server_address = ("127.0.0.1", 8766)
    with patch.object(launcher, "health", return_value={"service": "Inquisitio", "version": "0.4.2"}), patch.object(server_module, "InquisitioServer", side_effect=[OSError("busy"), fake_server]) as constructor, patch.object(launcher.threading, "Thread"):
        assert launcher.serve(ROOT, browser=False) == 0
    assert constructor.call_args_list[0].args[0][1] == 8765
    assert constructor.call_args_list[1].args[0][1] == 8766
    fake_server.serve_forever.assert_called_once()
    fake_server.server_close.assert_called_once()


def test_shell_syntax_and_packaged_runtime_integrity():
    subprocess.run(["bash", "-n", str(ROOT / "START_INQUISITIO_MAC.command")], check=True)
    app_launcher = ROOT / "Inquisitio.app/Contents/MacOS/Inquisitio"
    subprocess.run(["bash", "-n", str(app_launcher)], check=True)
    assert app_launcher.stat().st_mode & 0o111
    info = (ROOT / "Inquisitio.app/Contents/Info.plist").read_text()
    assert "<string>0.5.0</string>" in info
    vendor = ROOT / "vendor/macos-arm64"
    if not vendor.exists():
        pytest.skip("Native build source checkout does not include the offline distribution")
    assert launcher.sha256(vendor / "python.tar.gz") == (vendor / "runtime.sha256").read_text().strip()
    manifest = json.loads((vendor / "manifest.json").read_text())
    for profile in ("base", "full"):
        launcher.profile_fingerprint(vendor, manifest, profile)
        launcher.verify_wheels(vendor, manifest, profile)


def test_mac_launcher_prepares_verified_runtime_before_executing_it():
    script = (ROOT / "START_INQUISITIO_MAC.command").read_text()
    checksum = 'if [ "$ACTUAL_HASH" != "$EXPECTED_HASH" ]'
    extract = '/usr/bin/tar -xzf "$VENDOR/python.tar.gz"'
    prepare = 'prepare_runtime_for_macos "$STAGING/python"'
    probe = '"$STAGING/python/bin/python3" -I -c'
    assert script.index(checksum) < script.index(extract) < script.index(prepare) < script.index(probe)
    assert '/usr/bin/xattr -dr com.apple.quarantine "$runtime_root"' in script
    assert '/usr/bin/codesign --force --sign - "$candidate"' in script
    assert '/usr/bin/codesign --verify --strict "$candidate"' in script
    assert "-name '*.dylib'" in script and "-name '*.so'" in script


def test_each_mac_profile_contains_all_target_dependencies_and_compatible_wheels():
    import email
    import re
    import zipfile
    from packaging.markers import default_environment
    from packaging.requirements import Requirement
    from packaging.tags import compatible_tags, cpython_tags, mac_platforms
    from packaging.utils import parse_wheel_filename
    vendor = ROOT / "vendor/macos-arm64"
    if not vendor.exists():
        pytest.skip("Source checkout has no offline wheelhouse")
    manifest = json.loads((vendor / "manifest.json").read_text())
    normalize = lambda name: re.sub(r"[-_.]+", "-", name).lower()
    for profile, os_major in (("base", 11), ("full", 14)):
        platforms = list(mac_platforms(version=(os_major, 0), arch="arm64"))
        tags = set(cpython_tags(python_version=(3, 12), abis=["cp312", "abi3"], platforms=platforms))
        tags.update(compatible_tags(python_version=(3, 12), interpreter="cp312", platforms=platforms))
        versions = {normalize(name): value for name, value in manifest["profiles"][profile]["versions"].items()}
        environment = default_environment()
        environment.update(sys_platform="darwin", platform_system="Darwin", platform_machine="arm64", python_version="3.12", python_full_version="3.12.15", extra="")
        for filename in manifest["profiles"][profile]["wheels"]:
            assert parse_wheel_filename(filename)[3] & tags, filename
            with zipfile.ZipFile(vendor / "wheels" / filename) as archive:
                metadata = email.message_from_bytes(archive.read(next(n for n in archive.namelist() if n.endswith(".dist-info/METADATA"))))
            for line in metadata.get_all("Requires-Dist", []):
                requirement = Requirement(line)
                if requirement.marker and not requirement.marker.evaluate(environment):
                    continue
                assert normalize(requirement.name) in versions, (profile, metadata["Name"], line)
                assert versions[normalize(requirement.name)] in requirement.specifier


def test_bundled_python_is_a_mac_arm64_executable_with_relocatable_library_paths():
    import struct
    import tarfile
    archive = ROOT / "vendor/macos-arm64/python.tar.gz"
    if not archive.exists():
        pytest.skip("Source checkout has no bundled interpreter")
    with tarfile.open(archive) as tar:
        binary = tar.extractfile("python/bin/python3.12").read()
    magic, cpu, _, _, commands, _, _, _ = struct.unpack_from("<8I", binary)
    assert magic == 0xFEEDFACF and cpu == 0x0100000C  # Mach-O 64-bit, ARM64.
    offset = 32
    for _ in range(commands):
        command, size = struct.unpack_from("<II", binary, offset)
        if command in (0xC, 0x8000001C):  # LC_LOAD_DYLIB or LC_RPATH
            name_offset = struct.unpack_from("<I", binary, offset + 8)[0]
            value = binary[offset + name_offset:offset + size].split(b"\0", 1)[0].decode()
            assert value.startswith(("@", "/usr/lib/", "/System/Library/")), value
        offset += size
