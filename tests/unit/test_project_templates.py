from __future__ import annotations

import json
from pathlib import Path

import pytest

from figma_to_fgui.project_templates import TemplateCatalog, TemplateNotFound


def make_template(root: Path, *, template_id: str, version: str, platform: str) -> Path:
    template = root / template_id
    package = template / "Starter"
    package.mkdir(parents=True)
    (template / "template.json").write_text(
        json.dumps(
            {
                "template_id": template_id,
                "fairygui_version": version,
                "target_platform": platform,
                "display_name": "Starter project",
            }
        ),
        "utf-8",
    )
    (package / "package.xml").write_text("<package id='starter'><resources/></package>", "utf-8")
    return root


def test_catalog_lists_and_copies_only_declared_templates(tmp_path: Path) -> None:
    root = make_template(tmp_path, template_id="fgui-2024-web", version="2024.2", platform="web")
    (root / "not-a-template").mkdir()
    catalog = TemplateCatalog(root)

    assert catalog.list_options()[0].template_id == "fgui-2024-web"
    created = catalog.create("fgui-2024-web", "Quiz", tmp_path / "created")

    assert (created / "Quiz" / "package.xml").is_file()
    assert not (created / "template.json").exists()
    assert (root / "fgui-2024-web" / "Starter" / "package.xml").is_file()


def test_catalog_rejects_unknown_templates_and_symlinks(tmp_path: Path) -> None:
    root = make_template(tmp_path, template_id="fgui-2024-web", version="2024.2", platform="web")
    catalog = TemplateCatalog(root)

    with pytest.raises(TemplateNotFound):
        catalog.create("missing", "Quiz", tmp_path / "created")

    link = root / "fgui-2024-web" / "linked.xml"
    try:
        link.symlink_to(root / "fgui-2024-web" / "Starter" / "package.xml")
    except OSError:
        pytest.skip("symlinks are unavailable")
    with pytest.raises(ValueError, match="symlink"):
        catalog.create("fgui-2024-web", "Quiz", tmp_path / "created")
