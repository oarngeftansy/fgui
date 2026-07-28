import json
import time
from pathlib import Path

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
    data_dir: Path = Path(".figma-to-fgui"),
    fixtures_root: Path = Path("tests/fixtures"),
    rules: Path = Path("rules/default/classification.yaml"),
    host: str = "127.0.0.1",
    port: int = 8765,
) -> None:
    import uvicorn

    from figma_to_fgui.api import create_app

    uvicorn.run(create_app(data_dir, fixtures_root, rules), host=host, port=port)


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
