from __future__ import annotations

from pathlib import PurePosixPath

import pytest

from figma_to_fgui.fgui_new_project_ids import (
    TargetIdAllocator,
    TargetIdCollisionError,
    TargetNamingError,
    component_path,
    resource_path,
    validate_target_name,
    validate_unique_target_paths,
)


def allocate_all(requests: list[tuple[str, str]]) -> dict[tuple[str, str], str]:
    return TargetIdAllocator().allocate_all(requests)


def test_ids_do_not_depend_on_insertion_order() -> None:
    first = allocate_all([("component", "b"), ("component", "a")])
    second = allocate_all([("component", "a"), ("component", "b")])

    assert first == second
    assert all(len(target_id) == 8 and target_id.isascii() for target_id in first.values())
    assert all(set(target_id) <= set("0123456789abcdef") for target_id in first.values())


@pytest.mark.parametrize(
    "name",
    [
        "",
        ".",
        "..",
        "../Escape",
        "CON",
        "con.txt",
        "a/b",
        r"a\\b",
        "A\u0000B",
        "A\u001fB",
        "é/../x",
        "C:drive",
        "//server/share",
        "name.",
        "name ",
        "name?",
    ],
)
def test_target_names_fail_closed(name: str) -> None:
    with pytest.raises(TargetNamingError):
        validate_target_name(name, "component")


def test_validated_name_keeps_original_readable_spelling() -> None:
    decomposed = "Cafe\u0301"

    assert validate_target_name(decomposed, "component") == decomposed


def test_allocator_rejects_nfc_casefold_logical_key_collisions() -> None:
    with pytest.raises(TargetNamingError, match="case-insensitive"):
        allocate_all([("component", "Cafe\u0301"), ("component", "CAFÉ")])


def test_paths_are_posix_readable_and_stably_digest_qualified() -> None:
    target_id = TargetIdAllocator().allocate("component", "source:hero")

    assert component_path("Hero Button", target_id).as_posix() == (
        f"components/Hero Button-{target_id}.xml"
    )
    assert resource_path("Hero Art", target_id, ".png").as_posix() == (
        f"resources/Hero Art-{target_id}.png"
    )


def test_paths_remain_distinct_for_casefold_equivalent_readable_names() -> None:
    first_id = TargetIdAllocator().allocate("component", "source:first")
    second_id = TargetIdAllocator().allocate("component", "source:second")

    assert component_path("Hero", first_id).as_posix().casefold() != component_path(
        "hero", second_id
    ).as_posix().casefold()


@pytest.mark.parametrize(
    "paths",
    [
        (PurePosixPath("components", "Hero.xml"), PurePosixPath("components", "hero.xml")),
        (PurePosixPath("resources", "Café.png"), PurePosixPath("resources", "Cafe\u0301.png")),
        (PurePosixPath("components", "Hero.xml"), PurePosixPath("components", "Hero.xml")),
    ],
)
def test_unique_target_paths_fail_closed_for_casefold_or_nfc_collisions(
    paths: tuple[PurePosixPath, PurePosixPath],
) -> None:
    with pytest.raises(TargetNamingError, match="path collision"):
        validate_unique_target_paths(paths)


def test_unique_target_paths_allows_equal_filenames_in_different_directories() -> None:
    paths = (PurePosixPath("components", "Hero.xml"), PurePosixPath("resources", "Hero.xml"))

    assert validate_unique_target_paths(paths) == paths


@pytest.mark.parametrize(
    "paths",
    [
        (PurePosixPath("components", "Hero"), PurePosixPath("components", "Hero.")),
        (PurePosixPath("components", "Hero"), PurePosixPath("components", "Hero ")),
    ],
)
def test_unique_target_paths_fail_closed_for_windows_trailing_name_aliases(
    paths: tuple[PurePosixPath, PurePosixPath],
) -> None:
    with pytest.raises(TargetNamingError):
        validate_unique_target_paths(paths)


@pytest.mark.parametrize(
    "path",
    [
        PurePosixPath("components", "Hero."),
        PurePosixPath("components", "Hero "),
        PurePosixPath("components", "CON"),
        PurePosixPath("components", "COM¹.txt"),
    ],
)
def test_unique_target_paths_rejects_unsafe_windows_alias_segments(path: PurePosixPath) -> None:
    with pytest.raises(TargetNamingError):
        validate_unique_target_paths((path,))


def test_allocator_fails_closed_for_truncated_digest_collision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "figma_to_fgui.fgui_new_project_ids.id_digest",
        lambda kind, logical_key: "a" * 64,
    )

    with pytest.raises(TargetIdCollisionError) as captured:
        allocate_all([("component", "first"), ("resource", "second")])

    assert captured.value.collisions == (
        (("component", "first"), ("resource", "second")),
    )


@pytest.mark.parametrize(
    "suffix",
    ["png", "/png", ".png/../xml", ".pn\u0000g", ".png.exe", ".PNG", ".svg"],
)
def test_resource_path_rejects_unsafe_suffixes(suffix: str) -> None:
    with pytest.raises(TargetNamingError):
        resource_path("Hero", "0123abcd", suffix)


@pytest.mark.parametrize("name", ["COM¹", "com².txt", "LPT³", "lpt¹.xml"])
def test_target_names_reject_windows_superscript_device_names(name: str) -> None:
    with pytest.raises(TargetNamingError):
        validate_target_name(name, "component")


def test_component_filename_rejects_more_than_255_utf16_code_units() -> None:
    fitting = "😀" * 121
    too_long = "😀" * 122

    assert component_path(fitting, "0123abcd").name.endswith("-0123abcd.xml")
    with pytest.raises(TargetNamingError, match="too long"):
        component_path(too_long, "0123abcd")
