"""Fail-closed validation for self-contained SVG image resources."""

from __future__ import annotations

from lxml import etree

MAX_SVG_BYTES = 2 * 1024 * 1024
_FORBIDDEN_TAGS = {
    "script",
    "foreignobject",
    "animate",
    "animatetransform",
    "animatemotion",
    "set",
    "iframe",
    "object",
    "embed",
    "audio",
    "video",
    "style",
}


def validate_safe_svg(content: bytes) -> None:
    """Accept only bounded, inert SVG with internal fragment references."""
    if (
        len(content) > MAX_SVG_BYTES
        or b"<!DOCTYPE" in content.upper()
        or b"<!ENTITY" in content.upper()
    ):
        raise ValueError("invalid svg")
    try:
        root = etree.fromstring(
            content,
            etree.XMLParser(
                resolve_entities=False,
                no_network=True,
                load_dtd=False,
                huge_tree=False,
            ),
        )
    except (etree.XMLSyntaxError, ValueError) as error:
        raise ValueError("invalid svg") from error
    if etree.QName(root).localname.lower() != "svg":
        raise ValueError("invalid svg")
    for element in root.iter():
        if (
            not isinstance(element.tag, str)
            or etree.QName(element).localname.lower() in _FORBIDDEN_TAGS
        ):
            raise ValueError("invalid svg")
        for name, value in element.attrib.items():
            local_name = etree.QName(name).localname.lower()
            normalized = value.strip().lower()
            if (
                local_name.startswith("on")
                or local_name == "style"
                or (local_name in {"href", "src"} and not normalized.startswith("#"))
                or ("url(" in normalized and not normalized.startswith("url(#"))
            ):
                raise ValueError("invalid svg")
