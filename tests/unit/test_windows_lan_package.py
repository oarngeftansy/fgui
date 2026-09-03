import hashlib
import json
import os
import subprocess
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "packaging" / "windows-lan"


def test_lan_package_has_one_time_client_install_and_atomic_sync() -> None:
    installer = (PACKAGE / "client" / "Install-Client.ps1").read_text("utf-8")
    launcher = (PACKAGE / "client" / "Install-Client.cmd").read_text("utf-8")
    diagnostics = (PACKAGE / "client" / "Check-Client.ps1").read_text("utf-8")
    sync = (PACKAGE / "client" / "Sync-Plugin.ps1").read_text("utf-8")

    assert "FigmaToFGUI-ClientSync" in installer
    assert "Install-Client.ps1" in launcher and "ExecutionPolicy Bypass" in launcher
    assert "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run" in installer
    assert "/health" in diagnostics and "installed-release.txt" in diagnostics
    assert "manifest.json" in installer
    assert "current.json" in sync
    assert "SHA256" in sync
    assert "staging" in sync
    assert "backup" in sync
    assert "Get-Process" in sync and "Figma" in sync


def test_lan_server_install_limits_firewall_and_publishes_versioned_release() -> None:
    installer = (PACKAGE / "server" / "Install-Server.ps1").read_text("utf-8")
    gateway = (PACKAGE / "server" / "Caddyfile").read_text("utf-8")

    assert "LocalSubnet" in installer
    assert "192.168.50.210" in installer
    assert "current.json" in installer
    assert "SHA256" in installer
    assert "[string]$PythonPath" in installer
    assert "WindowsApps" in installer
    assert "venv\\Scripts\\python.exe" in installer
    assert "RandomNumberGenerator]::Create()" in installer
    assert "RandomNumberGenerator]::Fill" not in installer
    assert "client/releases" in gateway
    assert "FigmaToFGUI-Client.zip" in (PACKAGE / "build-package.ps1").read_text("utf-8")
    assert ".Replace('http://192.168.50.210:8780', $origin)" in installer


def test_client_sync_repairs_a_corrupted_installed_release(tmp_path: Path) -> None:
    release_id = "202609030001"
    server_root = tmp_path / "server" / "client" / "releases"
    version_root = server_root / release_id
    version_root.mkdir(parents=True)
    origin_holder: dict[str, str] = {}
    payloads = {
        "code.js": b"plugin code",
        "ui.html": b"<html>plugin</html>",
    }
    for name, payload in payloads.items():
        (version_root / name).write_bytes(payload)
    handler = partial(SimpleHTTPRequestHandler, directory=str(tmp_path / "server"))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    origin_holder["origin"] = f"http://127.0.0.1:{server.server_port}"
    manifest = json.dumps(
        {"id": "123456789", "networkAccess": {"allowedDomains": [origin_holder["origin"]]}},
        separators=(",", ":"),
    ).encode()
    (version_root / "manifest.json").write_bytes(manifest)
    files = {}
    for path in version_root.iterdir():
        payload = path.read_bytes()
        files[path.name] = {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
    (server_root / "current.json").write_text(
        json.dumps({"schemaVersion": 1, "releaseId": release_id, "files": files}), "utf-8"
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    environment = os.environ.copy()
    environment["LOCALAPPDATA"] = str(tmp_path / "client")
    command = [
        "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
        str(PACKAGE / "client" / "Sync-Plugin.ps1"), "-ServerOrigin", origin_holder["origin"], "-Force",
    ]
    try:
        first = subprocess.run(command, env=environment, capture_output=True, text=True, check=False)
        assert first.returncode == 0, first.stdout + first.stderr
        installed = tmp_path / "client" / "FigmaToFGUI" / "plugin" / "code.js"
        installed.write_bytes(b"corrupted")
        second = subprocess.run(command, env=environment, capture_output=True, text=True, check=False)
        assert second.returncode == 0, second.stdout + second.stderr
        assert installed.read_bytes() == payloads["code.js"]
    finally:
        server.shutdown()
        server.server_close()
