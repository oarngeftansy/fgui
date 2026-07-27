import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from figma_to_fgui.changeset import build_changeset
from figma_to_fgui.classify import classify_tree
from figma_to_fgui.generate import generate_staging
from figma_to_fgui.models import ChangeSet
from figma_to_fgui.normalize import normalize_document
from figma_to_fgui.project_index import index_project
from figma_to_fgui.rules import load_rules
from figma_to_fgui.validate import validate_staging


class ConversionRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    figma_json: Path
    project_root: Path
    package_name: str
    staging_root: Path
    classification_rules: Path


def convert(request: ConversionRequest) -> ChangeSet:
    raw = json.loads(request.figma_json.read_text("utf-8"))
    roots, normalization_diagnostics = normalize_document(raw)
    index = index_project(request.project_root)
    decisions = classify_tree(roots, load_rules(request.classification_rules))
    _, generation_diagnostics = generate_staging(
        roots, decisions, request.package_name, request.staging_root
    )
    validation_diagnostics = validate_staging(request.staging_root, index)
    diagnostics = normalization_diagnostics + generation_diagnostics + validation_diagnostics
    return build_changeset(request.project_root, request.staging_root, diagnostics)
