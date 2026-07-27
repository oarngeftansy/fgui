import json
from pathlib import Path

import typer

from figma_to_fgui.classify import classify_tree
from figma_to_fgui.normalize import normalize_document
from figma_to_fgui.pipeline import ConversionRequest, convert
from figma_to_fgui.project_index import index_project
from figma_to_fgui.rules import load_rules
from figma_to_fgui.validate import has_errors, validate_staging

app = typer.Typer(no_args_is_help=True)


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


if __name__ == "__main__":
    app()
