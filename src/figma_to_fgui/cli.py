import hmac
import ipaddress
import json
import os
import time
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

import typer

from figma_to_fgui.classify import classify_tree
from figma_to_fgui.normalize import normalize_document
from figma_to_fgui.pipeline import ConversionRequest, convert
from figma_to_fgui.project_index import index_project
from figma_to_fgui.rules import load_rules
from figma_to_fgui.validate import has_errors, validate_staging

app = typer.Typer(no_args_is_help=True)
agent_app = typer.Typer(no_args_is_help=True)
app.add_typer(agent_app, name="agent")


def _production_origin(value: str) -> str:
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError as error:
        raise typer.BadParameter(
            "must be exactly one HTTPS origin", param_hint="--public-origin"
        ) from error
    if (
        "*" in value
        or "," in value
        or parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise typer.BadParameter("must be exactly one HTTPS origin", param_hint="--public-origin")
    return f"https://{parsed.netloc}"


def _secret_file(secret_file: Path | None, option: str) -> bytes:
    if secret_file is None:
        raise typer.BadParameter("is required in production", param_hint=option)
    try:
        if not secret_file.is_file():
            raise OSError
        secret = secret_file.read_bytes()
    except OSError as error:
        raise typer.BadParameter("must name a readable regular file", param_hint=option) from error
    if len(secret) < 32:
        raise typer.BadParameter("must contain at least 32 bytes", param_hint=option)
    return secret


def _plugin_access_token_file(secret_file: Path | None) -> bytes:
    token = _secret_file(secret_file, "--plugin-access-token-file")
    if len(token) > 256 or any(byte < 0x21 or byte > 0x7E for byte in token):
        raise typer.BadParameter(
            "must contain 32-256 printable ASCII characters",
            param_hint="--plugin-access-token-file",
        )
    return token


def _validate_plugin_manifest(path: Path | None, public_origin: str) -> None:
    if path is None:
        raise typer.BadParameter("is required in production", param_hint="--plugin-manifest")
    try:
        manifest = json.loads(path.read_text("utf-8"))
        plugin_id = manifest["id"]
        domains = manifest["networkAccess"]["allowedDomains"]
    except (OSError, TypeError, ValueError, KeyError):
        raise typer.BadParameter("must be a readable production plugin manifest", param_hint="--plugin-manifest") from None
    if not isinstance(plugin_id, str) or not plugin_id.isdecimal() or domains != [public_origin]:
        raise typer.BadParameter(
            "must allow exactly the configured public origin", param_hint="--plugin-manifest"
        )


def _trusted_proxy(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return str(ipaddress.ip_address(value))
    except ValueError as error:
        raise typer.BadParameter(
            "must be one explicit proxy IP address", param_hint="--trusted-proxy"
        ) from error


def _write_json(output: Path, value: object) -> None:
    output.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2),
        "utf-8",
    )


@app.command("normalize")
def normalize_command(source: Path, output: Path) -> None:
    roots, diagnostics = normalize_document(json.loads(source.read_text("utf-8")))
    _write_json(
        output,
        {
            "roots": [root.model_dump(mode="json") for root in roots],
            "diagnostics": [item.model_dump(mode="json") for item in diagnostics],
        },
    )


@app.command("index-project")
def index_project_command(project_root: Path, output: Path) -> None:
    _write_json(output, index_project(project_root).model_dump(mode="json"))


@app.command("classify")
def classify_command(source: Path, rules: Path, output: Path) -> None:
    roots, _ = normalize_document(json.loads(source.read_text("utf-8")))
    decisions = classify_tree(roots, load_rules(rules))
    _write_json(output, [item.model_dump(mode="json") for item in decisions])


@app.command("validate")
def validate_command(staging_root: Path, project_root: Path, output: Path) -> None:
    diagnostics = validate_staging(staging_root, index_project(project_root))
    _write_json(output, [item.model_dump(mode="json") for item in diagnostics])
    if has_errors(diagnostics):
        raise typer.Exit(code=2)


@app.command("convert")
def convert_command(
    figma_json: Path,
    project_root: Path,
    package_name: str,
    staging_root: Path,
    output: Path,
    rules: Path = Path("rules/default/classification.yaml"),
) -> None:
    result = convert(
        ConversionRequest(
            figma_json=figma_json,
            project_root=project_root,
            package_name=package_name,
            staging_root=staging_root,
            classification_rules=rules,
        )
    )
    _write_json(output, result.model_dump(mode="json"))
    if not result.applicable:
        raise typer.Exit(code=2)


@app.command("serve")
def serve_command(
    data_dir: Path | None = None,
    fixtures_root: Path = Path("tests/fixtures"),
    rules: Path = Path("rules/default/classification.yaml"),
    web_dist: Path | None = None,
    production: bool = False,
    public_origin: str | None = None,
    plugin_access_token_file: Path | None = None,
    gateway_secret_file: Path | None = None,
    plugin_manifest: Path | None = None,
    templates_root: Path | None = None,
    trusted_proxy: str | None = None,
    host: str = "127.0.0.1",
    port: int = 8765,
    health_instance_token: Annotated[
        str | None,
        typer.Option(hidden=True, envvar="FIGMA_TO_FGUI_HEALTH_INSTANCE_TOKEN"),
    ] = None,
) -> None:
    configured_data_dir = data_dir or Path(".figma-to-fgui")
    if web_dist is not None and (
        not web_dist.is_dir()
        or not (web_dist / "index.html").is_file()
        or not (web_dist / "assets").is_dir()
    ):
        raise typer.BadParameter(
            "must contain index.html and an assets directory",
            param_hint="--web-dist",
        )
    origin: str | None = None
    plugin_access_token: bytes | None = None
    gateway_secret: bytes | None = None
    if production:
        if public_origin is None:
            raise typer.BadParameter("is required in production", param_hint="--public-origin")
        if web_dist is None:
            raise typer.BadParameter("is required in production", param_hint="--web-dist")
        if data_dir is None:
            raise typer.BadParameter("is required in production", param_hint="--data-dir")
        if host != "127.0.0.1":
            raise typer.BadParameter("must be 127.0.0.1 in production", param_hint="--host")
        origin = _production_origin(public_origin)
        plugin_access_token = _plugin_access_token_file(plugin_access_token_file)
        gateway_secret = _secret_file(gateway_secret_file, "--gateway-secret-file")
        if hmac.compare_digest(plugin_access_token, gateway_secret):
            raise typer.BadParameter(
                "must differ from the plugin access token", param_hint="--gateway-secret-file"
            )
        _validate_plugin_manifest(plugin_manifest, origin)
    elif (
        public_origin is not None
        or gateway_secret_file is not None
        or plugin_manifest is not None
    ):
        raise typer.BadParameter("requires --production", param_hint="--production")
    elif plugin_access_token_file is not None:
        plugin_access_token = _plugin_access_token_file(plugin_access_token_file)
    proxy = _trusted_proxy(trusted_proxy)

    import uvicorn

    from figma_to_fgui.api import create_app
    from figma_to_fgui.semantic_config import (
        build_semantic_analyzer,
        load_semantic_service_settings,
    )

    semantic_analyzer = build_semantic_analyzer(load_semantic_service_settings(os.environ))
    try:
        application = create_app(
            configured_data_dir,
            fixtures_root,
            rules,
            web_dist=web_dist,
            health_instance_token=health_instance_token,
            plugin_access_token=plugin_access_token,
            gateway_secret=gateway_secret,
            public_origin=origin,
            allow_fixture_jobs=not production,
            templates_root=templates_root,
            semantic_analyzer=semantic_analyzer,
        )
        uvicorn.run(
            application,
            host=host,
            port=port,
            proxy_headers=proxy is not None,
            forwarded_allow_ips=proxy or "",
        )
    finally:
        if semantic_analyzer is not None:
            semantic_analyzer.close()


@agent_app.command("register")
def agent_register(
    agent_id: str,
    name: str,
    api_url: str = "http://127.0.0.1:8765",
    config_path: Path | None = None,
) -> None:
    from figma_to_fgui.agent import AgentClient, AgentConfig, default_config_path

    path = config_path or default_config_path()
    config = AgentConfig(agent_id=agent_id, name=name, api_url=api_url)
    AgentClient(config).register()
    config.save(path)


@agent_app.command("bind")
def agent_bind(project_id: str, path: Path, config_path: Path | None = None) -> None:
    from figma_to_fgui.agent import (
        AgentClient,
        AgentConfig,
        bind_local_project,
        default_config_path,
    )

    target = config_path or default_config_path()
    config = AgentConfig.load(target)
    AgentClient(config).bind(project_id)
    updated = config.model_copy(
        update={"projects": {**config.projects, project_id: bind_local_project(path)}}
    )
    updated.save(target)


@agent_app.command("poll")
def agent_poll(once: bool = True, config_path: Path | None = None) -> None:
    from figma_to_fgui.agent import AgentClient, AgentConfig, default_config_path

    config = AgentConfig.load(config_path or default_config_path())
    client = AgentClient(config)
    if once:
        result = client.poll_once()
        typer.echo("No approved job." if result is None else result.model_dump_json(indent=2))


@agent_app.command("run")
def agent_run(interval: float = 5, config_path: Path | None = None) -> None:
    import httpx

    from figma_to_fgui.agent import AgentClient, AgentConfig, default_config_path

    client = AgentClient(AgentConfig.load(config_path or default_config_path()))
    while True:
        try:
            client.poll_once()
        except httpx.HTTPError:
            pass
        time.sleep(interval)


if __name__ == "__main__":
    app()
