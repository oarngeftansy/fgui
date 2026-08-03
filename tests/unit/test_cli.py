import json
from pathlib import Path

import uvicorn
from pytest import MonkeyPatch
from typer.testing import CliRunner

from figma_to_fgui.agent import AgentClient, AgentConfig
from figma_to_fgui.cli import app
from figma_to_fgui.semantic_config import SemanticConfigurationError
from figma_to_fgui.service_contracts import ApplyResult, ApplyStatus


def test_help_lists_all_atomic_commands() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("normalize", "index-project", "classify", "validate", "convert", "serve", "agent"):
        assert command in result.stdout


def test_agent_poll_prints_terminal_result(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    config = AgentConfig(agent_id="agent-1", name="Desk")
    result = ApplyResult(
        job_id="job-1",
        agent_id="agent-1",
        project_id="project-1",
        status=ApplyStatus.APPLIED,
        changed_paths=("Sample/Main.xml",),
    )
    monkeypatch.setattr(AgentConfig, "load", classmethod(lambda cls, path: config))
    monkeypatch.setattr(AgentClient, "poll_once", lambda self: result)

    invoked = CliRunner().invoke(
        app,
        ["agent", "poll", "--config-path", str(tmp_path / "agent.json")],
    )
    assert invoked.exit_code == 0
    assert '"status": "applied"' in invoked.stdout
    assert "Sample/Main.xml" in invoked.stdout


def test_serve_accepts_a_built_web_console_directory(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    from figma_to_fgui import api

    captured: dict[str, object] = {}
    web_dist = tmp_path / "dist"
    web_dist.mkdir()
    (web_dist / "assets").mkdir()
    (web_dist / "index.html").write_text("<div id='root'></div>", "utf-8")
    monkeypatch.setattr(api, "create_app", lambda *args, **kwargs: captured.update(kwargs) or object())
    monkeypatch.setattr(uvicorn, "run", lambda application, **kwargs: captured.update(run=kwargs))

    result = CliRunner().invoke(
        app,
        [
            "serve",
            "--web-dist",
            str(web_dist),
        ],
        env={"FIGMA_TO_FGUI_HEALTH_INSTANCE_TOKEN": "test-instance-token"},
    )

    assert result.exit_code == 0, result.stdout
    assert captured["web_dist"] == web_dist
    assert captured["health_instance_token"] == "test-instance-token"
    assert captured["run"] == {
        "host": "127.0.0.1", "port": 8765, "proxy_headers": False, "forwarded_allow_ips": ""
    }
    assert "--health-instance-token" not in CliRunner().invoke(app, ["serve", "--help"]).stdout


def test_serve_passes_the_configured_templates_root(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    from figma_to_fgui import api

    captured: dict[str, object] = {}
    templates = tmp_path / "templates"
    monkeypatch.setattr(api, "create_app", lambda *args, **kwargs: captured.update(kwargs) or object())
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: None)

    result = CliRunner().invoke(app, ["serve", "--templates-root", str(templates)])

    assert result.exit_code == 0, result.output
    assert captured["templates_root"] == templates


def test_serve_fails_before_uvicorn_when_enabled_ai_configuration_is_incomplete(
    monkeypatch: MonkeyPatch,
) -> None:
    started: list[object] = []
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: started.append(args))

    result = CliRunner().invoke(
        app,
        ["serve"],
        env={
            "AI_SEMANTIC_ENABLED": "true",
            "AI_SEMANTIC_PROVIDER": "openai",
            "AI_SEMANTIC_BASE_URL": "https://api.openai.com/v1",
            "AI_SEMANTIC_MODEL": "test-model",
            "AI_SEMANTIC_API_KEY": "",
        },
    )

    assert result.exit_code == 1
    assert isinstance(result.exception, SemanticConfigurationError)
    assert "AI_SEMANTIC_API_KEY" in str(result.exception)
    assert started == []


def test_serve_closes_the_configured_ai_analyzer_when_server_stops(
    monkeypatch: MonkeyPatch,
) -> None:
    from figma_to_fgui import api, semantic_config

    closed: list[bool] = []

    class Analyzer:
        def close(self) -> None:
            closed.append(True)

    monkeypatch.setattr(api, "create_app", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        semantic_config,
        "build_semantic_analyzer",
        lambda settings: Analyzer(),
    )
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: None)

    result = CliRunner().invoke(app, ["serve"])

    assert result.exit_code == 0, result.output
    assert closed == [True]


def test_serve_reports_invalid_web_build_as_a_typer_parameter_error(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["serve", "--web-dist", str(tmp_path / "missing")])

    assert result.exit_code == 2
    assert isinstance(result.exception, SystemExit)
    assert "Usage:" in result.output
    assert "--web-dist" in result.output
    assert "Traceback" not in result.output


def _production_files(tmp_path: Path, origin: str = "https://fgui.corp.example") -> tuple[Path, Path, Path]:
    web_dist = tmp_path / "web-dist"
    web_dist.mkdir()
    (web_dist / "assets").mkdir()
    (web_dist / "index.html").write_text("<div id='root'></div>", "utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"id": "123456789", "networkAccess": {"allowedDomains": [origin]}}),
        "utf-8",
    )
    secret = tmp_path / "plugin-secret.bin"
    secret.write_bytes(b"s" * 32)
    return web_dist, manifest, secret


def _gateway_secret(tmp_path: Path, value: bytes = b"g" * 32) -> Path:
    secret = tmp_path / "gateway-secret.bin"
    secret.write_bytes(value)
    return secret


def test_production_rejects_non_ascii_plugin_access_token(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: None)
    web_dist, manifest, token = _production_files(tmp_path)
    token.write_bytes(bytes(range(32)))
    gateway = _gateway_secret(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "serve", "--production", "--data-dir", str(tmp_path / "data"),
            "--public-origin", "https://fgui.corp.example",
            "--plugin-access-token-file", str(token),
            "--gateway-secret-file", str(gateway), "--web-dist", str(web_dist),
            "--plugin-manifest", str(manifest),
        ],
    )

    assert result.exit_code == 2
    assert "--plugin-access-token-file" in result.output


def test_production_serve_requires_safe_complete_configuration(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: None)
    result = CliRunner().invoke(app, ["serve", "--production"])

    assert result.exit_code == 2
    assert "--public-origin" in result.output
    assert "Traceback" not in result.output

    web_dist, manifest, secret = _production_files(tmp_path)
    result = CliRunner().invoke(
        app,
        [
            "serve", "--production", "--public-origin", "https://fgui.corp.example",
            "--plugin-access-token-file", str(secret), "--web-dist", str(web_dist),
            "--plugin-manifest", str(manifest),
        ],
    )
    assert result.exit_code == 2
    assert "--data-dir" in result.output

    result = CliRunner().invoke(
        app,
        [
            "serve", "--production", "--data-dir", str(tmp_path / "data"),
            "--public-origin", "https://fgui.corp.example", "--plugin-access-token-file", str(secret),
            "--web-dist", str(web_dist), "--plugin-manifest", str(manifest),
        ],
    )
    assert result.exit_code == 2
    assert "--gateway-secret-file" in result.output

    for option, unsafe in (
        ("--public-origin", "http://fgui.corp.example"),
        ("--public-origin", "https://one.example,https://two.example"),
        ("--public-origin", "https://*.corp.example"),
    ):
        result = CliRunner().invoke(
            app,
            [
                "serve", "--production", option, unsafe, "--plugin-access-token-file", str(secret),
                "--data-dir", str(tmp_path / "data"), "--web-dist", str(web_dist),
                "--plugin-manifest", str(manifest),
            ],
        )
        assert result.exit_code == 2
        assert "--public-origin" in result.output
        assert "Traceback" not in result.output


def test_production_serve_keeps_the_application_on_loopback(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: None)
    web_dist, manifest, secret = _production_files(tmp_path)
    result = CliRunner().invoke(
        app,
        [
            "serve", "--production", "--data-dir", str(tmp_path / "data"),
            "--public-origin", "https://fgui.corp.example", "--plugin-access-token-file", str(secret),
            "--web-dist", str(web_dist), "--plugin-manifest", str(manifest), "--host", "0.0.0.0",
        ],
    )

    assert result.exit_code == 2
    assert "--host" in result.output
    assert "Traceback" not in result.output


def test_production_serve_rejects_unsafe_secret_and_manifest_without_disclosure(tmp_path: Path) -> None:
    web_dist, manifest, secret = _production_files(tmp_path)
    gateway_secret = _gateway_secret(tmp_path)
    secret.write_bytes(b"short")
    result = CliRunner().invoke(
        app,
        [
            "serve", "--production", "--public-origin", "https://fgui.corp.example",
            "--data-dir", str(tmp_path / "data"), "--plugin-access-token-file", str(secret), "--web-dist", str(web_dist),
            "--plugin-manifest", str(manifest), "--gateway-secret-file", str(gateway_secret),
        ],
    )

    assert result.exit_code == 2
    assert "--plugin-access-token-file" in result.output
    assert str(secret) not in result.output
    assert "short" not in result.output
    assert "Traceback" not in result.output

    secret.write_bytes(b"s" * 32)
    manifest.write_text(json.dumps({"id": "123456789", "networkAccess": {"allowedDomains": ["https://wrong.example"]}}), "utf-8")
    result = CliRunner().invoke(
        app,
        [
            "serve", "--production", "--public-origin", "https://fgui.corp.example",
            "--data-dir", str(tmp_path / "data"), "--plugin-access-token-file", str(secret), "--web-dist", str(web_dist),
            "--plugin-manifest", str(manifest), "--gateway-secret-file", str(gateway_secret),
        ],
    )

    assert result.exit_code == 2
    assert "--plugin-manifest" in result.output
    assert str(manifest) not in result.output
    assert "Traceback" not in result.output


def test_production_serve_requires_a_distinct_full_length_gateway_secret(tmp_path: Path) -> None:
    web_dist, manifest, plugin_secret = _production_files(tmp_path)
    gateway_secret = _gateway_secret(tmp_path, b"short")
    command = [
        "serve", "--production", "--data-dir", str(tmp_path / "data"),
        "--public-origin", "https://fgui.corp.example", "--plugin-access-token-file", str(plugin_secret),
        "--gateway-secret-file", str(gateway_secret), "--web-dist", str(web_dist),
        "--plugin-manifest", str(manifest),
    ]
    short = CliRunner().invoke(app, command)

    assert short.exit_code == 2
    assert "--gateway-secret-file" in short.output
    assert str(gateway_secret) not in short.output
    assert "Traceback" not in short.output

    gateway_secret.write_bytes(plugin_secret.read_bytes())
    same = CliRunner().invoke(app, command)

    assert same.exit_code == 2
    assert "--gateway-secret-file" in same.output
    assert "Traceback" not in same.output


def test_production_serve_configures_single_origin_without_fixture_jobs(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    from figma_to_fgui import api

    captured: dict[str, object] = {}
    web_dist, manifest, secret = _production_files(tmp_path)
    gateway_secret = _gateway_secret(tmp_path)
    monkeypatch.setattr(api, "create_app", lambda *args, **kwargs: captured.update(kwargs) or object())
    monkeypatch.setattr(uvicorn, "run", lambda application, **kwargs: captured.update(run=kwargs))

    result = CliRunner().invoke(
        app,
        [
            "serve", "--production", "--public-origin", "https://fgui.corp.example",
            "--data-dir", str(tmp_path / "data"), "--plugin-access-token-file", str(secret), "--web-dist", str(web_dist),
            "--plugin-manifest", str(manifest), "--gateway-secret-file", str(gateway_secret),
            "--trusted-proxy", "10.0.0.7",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["plugin_access_token"] == b"s" * 32
    assert captured["gateway_secret"] == b"g" * 32
    assert captured["public_origin"] == "https://fgui.corp.example"
    assert captured["allow_fixture_jobs"] is False
    assert captured["run"] == {
        "host": "127.0.0.1", "port": 8765, "proxy_headers": True,
        "forwarded_allow_ips": "10.0.0.7",
    }
