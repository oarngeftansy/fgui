from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_local_launcher_is_loopback_only_and_keeps_machine_state_untracked() -> None:
    script = (ROOT / "Start-Local.ps1").read_text(encoding="utf-8")
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert "http://localhost:8765" in script
    assert "--host 127.0.0.1" in script
    assert "--port 8765" in script
    assert "--production" not in script
    assert "cloudflared" not in script.casefold()
    assert ".local-run/" in ignore
    assert "RandomNumberGenerator" in script
    assert "plugin-access-token.txt" in script


def test_local_launcher_handoff_is_one_click_and_documents_manifest() -> None:
    command = (ROOT / "启动本机版.cmd").read_text(encoding="utf-8")
    guide = (ROOT / "docs/deployment/git-clone-local-windows.md").read_text(
        encoding="utf-8"
    )

    assert "Start-Local.ps1" in command
    assert "-ExecutionPolicy Bypass" in command
    assert "git clone <private-repository-url> C:\\src\\figma-to-fgui" in guide
    assert ".local-run\\plugin\\manifest.json" in guide
    assert "http://localhost:8765" in guide


def test_local_launcher_requires_ascii_checkout_before_mutating_dependencies() -> None:
    script = (ROOT / "Start-Local.ps1").read_text(encoding="utf-8")

    ascii_guard = script.index("$repo -match '[^\\x00-\\x7F]'")
    local_directory_creation = script.index("CreateDirectory($localRoot)")
    dependency_install = script.index("pip install")
    assert ascii_guard < local_directory_creation < dependency_install
