from __future__ import annotations

import pytest

from figma_to_fgui.fgui_new_project_ids import (
    TargetIdAllocator,
    TargetIdCollisionError,
    TargetNamingError,
    component_path,
    resource_path,
    validate_target_name,
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


@pytest.mark.parametrize("suffix", ["png", "/png", ".png/../xml", ".pn\u0000g"])
def test_resource_path_rejects_unsafe_suffixes(suffix: str) -> None:
    with pytest.raises(TargetNamingError):
        resource_path("Hero", "0123abcd", suffix)
