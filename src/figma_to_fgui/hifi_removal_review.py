"""Policy 28 §8-§11: Legacy Removal Review.

A REMOVE_CANDIDATE is never deleted silently. Candidates are grouped by
semantic root and page region, ordered by runtime risk, and at most five
groups are presented for user confirmation (§10). Overflow groups of pure
low-risk visuals auto-adopt their recommendation and stay fully recorded in
the report; objects bound to program logic, controllers, gears, transitions
or runtime parameters are never auto-removed.
"""
from __future__ import annotations

import base64
import hashlib
import io
from pathlib import Path
from typing import Literal

from lxml import etree
from PIL import Image, ImageDraw, ImageFont
from pydantic import Field, field_validator

from figma_to_fgui.hifi_replacement_models import (
    FguiComponentInventory,
    FguiObjectRef,
    HifiMappingDraft,
)
from figma_to_fgui.service_contracts import StrictVersionedModel

RemovalDecision = Literal["remove", "preserve"]

MAX_USER_FACING_GROUPS = 5

_TIER_RUNTIME = 1
_TIER_CONTROLLER = 2
_TIER_COMPONENT = 3
_TIER_VISIBLE = 4
_TIER_PLAIN = 5


class HifiRemovalObject(StrictVersionedModel):
    item_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")
    object_id: str = Field(min_length=1, max_length=128)
    name: str = Field(max_length=256)
    object_type: str = Field(max_length=32)
    risk_tier: int = Field(ge=1, le=5)
    reason: str = Field(min_length=1, max_length=500)
    controller_refs: tuple[str, ...] = ()
    transition_refs: tuple[str, ...] = ()
    relation_refs: tuple[str, ...] = ()
    referenced_by: tuple[str, ...] = ()
    runtime_bound: bool = False
    preview_url: str = Field(default="", max_length=262144)
    text: str = Field(default="", max_length=256)
    size: tuple[float, float] | None = None
    location: str = Field(default="", max_length=256)


class HifiRemovalGroup(StrictVersionedModel):
    group_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,64}$")
    semantic_root: str = Field(min_length=1, max_length=256)
    region: str = Field(default="", max_length=256)
    risk_tier: int = Field(ge=1, le=5)
    recommendation: RemovalDecision
    auto_resolved: bool = False
    objects: tuple[HifiRemovalObject, ...]
    merged_template: bool = False


class HifiRemovalReview(StrictVersionedModel):
    pending: bool = False
    total_candidate_count: int = Field(default=0, ge=0)
    groups: tuple[HifiRemovalGroup, ...] = ()
    auto_resolved_groups: tuple[HifiRemovalGroup, ...] = ()


class HifiRemovalGroupDecision(StrictVersionedModel):
    group_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,64}$")
    decision: RemovalDecision


class HifiRemovalDecisionRequest(StrictVersionedModel):
    mapping_revision: int = Field(ge=1)
    decisions: tuple[HifiRemovalGroupDecision, ...]

    @field_validator("decisions", mode="before")
    @classmethod
    def _accept_json_array(cls, value: object) -> object:
        # JSON has no tuple literal: the console posts an array. Convert at
        # the wire boundary so strict tuple validation still applies inside.
        if isinstance(value, list):
            return tuple(value)
        return value


PREVIEW_MAX_EDGE = 80
PREVIEW_OBJECT_LIMIT = 32


def _package_image_paths(root: Path) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    manifests = [*(root.glob("*/package.xml")), *(root.glob("assets/*/package.xml"))]
    for manifest in manifests:
        try:
            document = etree.parse(str(manifest)).getroot()
        except (OSError, etree.XMLSyntaxError):
            continue
        for entry in document.xpath("./resources/image"):
            relative = (
                Path(str(entry.attrib.get("path", "/")).strip("/"))
                / str(entry.attrib.get("name", ""))
            )
            candidate = (manifest.parent / relative).resolve()
            if candidate.is_file():
                paths.setdefault(str(entry.get("id")), candidate)
    return paths


def _preview_data_url(path: Path, cache: dict[Path, str]) -> str:
    cached = cache.get(path)
    if cached is not None:
        return cached
    with Image.open(path) as opened:
        preview = opened.convert("RGBA")
    preview.thumbnail((PREVIEW_MAX_EDGE, PREVIEW_MAX_EDGE), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    preview.save(buffer, format="PNG")
    url = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
    cache[path] = url
    return url



REGION_MAX_EDGE = 220
REGION_PADDING = 48

_FONT_CACHE: dict[int, object] = {}


def _preview_font(size: int) -> object:
    font = _FONT_CACHE.get(size)
    if font is None:
        try:
            font = ImageFont.truetype(
                "C:\Windows\Fonts\msyh.ttc", max(9, min(size, 48))
            )
        except OSError:
            font = ImageFont.load_default()
        _FONT_CACHE[size] = font
    return font


def _argb(value: str | None) -> tuple[int, int, int, int] | None:
    if not value:
        return None
    hex_color = value.lstrip("#")
    try:
        if len(hex_color) == 8:
            alpha, red, green, blue = (
                int(hex_color[index:index + 2], 16) for index in (0, 2, 4, 6)
            )
            return (red, green, blue, alpha)
        if len(hex_color) == 6:
            red, green, blue = (
                int(hex_color[index:index + 2], 16) for index in (0, 2, 4)
            )
            return (red, green, blue, 255)
    except ValueError:
        return None
    return None


def _pair(value: str | None) -> tuple[float, float]:
    if not value:
        return (0.0, 0.0)
    parts = [float(part) for part in value.split(",")[:2]]
    return (parts[0], parts[1] if len(parts) > 1 else 0.0)


def _element_size(element: etree._Element) -> tuple[float, float] | None:
    if not element.get("size"):
        return None
    width, height = _pair(element.get("size"))
    if width <= 0 or height <= 0:
        return None
    return (width, height)


def _render_component_region(
    root: Path,
    component_path: str | None,
    focus: tuple[float, float, float, float],
    image_paths: dict[str, Path],
) -> str | None:
    """Flat best-effort render of the old component cropped around focus."""
    if not component_path:
        return None
    source = (root / component_path).resolve()
    if not source.is_relative_to(root.resolve()) or not source.is_file():
        return None
    try:
        document = etree.parse(str(source)).getroot()
    except (OSError, etree.XMLSyntaxError):
        return None
    canvas_width, canvas_height = _pair(document.get("size", "400,300"))
    if canvas_width <= 0 or canvas_height <= 0:
        return None
    canvas = Image.new(
        "RGBA", (int(canvas_width), int(canvas_height)), (255, 255, 255, 0)
    )
    draw = ImageDraw.Draw(canvas)
    for element in document.xpath("./displayList/*"):
        if element.get("visible") == "false":
            continue
        tag = str(element.tag)
        x, y = _pair(element.get("xy"))
        size = _element_size(element)
        if tag == "image" and element.get("src"):
            path = image_paths.get(str(element.attrib["src"]))
            if path is not None:
                try:
                    with Image.open(path) as opened:
                        texture = opened.convert("RGBA").copy()
                except OSError:
                    texture = None
                if texture is not None:
                    width, height = size or texture.size
                    if (
                        abs(width - texture.width) > 0.5
                        or abs(height - texture.height) > 0.5
                    ):
                        texture = texture.resize(
                            (max(1, int(width)), max(1, int(height))),
                            Image.Resampling.BILINEAR,
                        )
                    canvas.paste(texture, (int(x), int(y)), texture)
                    continue
        if tag in {"text", "richtext"}:
            content = element.get("text") or ""
            if content:
                font_size = int(float(element.get("fontSize", "12") or 12))
                color = _argb(element.get("color")) or (33, 37, 41, 255)
                draw.text(
                    (x, y), content[:60], font=_preview_font(font_size), fill=color
                )
                continue
        if tag == "graph":
            width, height = size or (20.0, 20.0)
            fill = _argb(element.get("fillColor")) or (148, 163, 184, 255)
            outline = _argb(element.get("lineColor"))
            line_width = int(float(element.get("lineSize", "0") or 0))
            shape = element.get("type", "rect")
            box = [x, y, x + width, y + height]
            if shape == "ellipse":
                draw.ellipse(box, fill=fill, outline=outline, width=line_width)
            elif shape == "polygon" and element.get("points"):
                points = []
                pairs = element.get("points", "").replace(";", ",").split(",")
                numbers = [float(part) for part in pairs if part.strip()]
                for index in range(0, len(numbers) - 1, 2):
                    points.append((x + numbers[index], y + numbers[index + 1]))
                if len(points) >= 3:
                    draw.polygon(points, fill=fill, outline=outline)
            else:
                draw.rectangle(box, fill=fill, outline=outline, width=line_width)
            continue
        if tag in {"component", "loader", "list", "movieclip"} and size:
            draw.rectangle(
                [x, y, x + size[0], y + size[1]], fill=(148, 163, 184, 70)
            )
    draw.rectangle(
        [
            focus[0],
            focus[1],
            focus[0] + focus[2],
            focus[1] + focus[3],
        ],
        outline=(220, 38, 38, 255),
        width=3,
    )
    left = max(0.0, focus[0] - REGION_PADDING)
    top = max(0.0, focus[1] - REGION_PADDING)
    right = min(float(canvas.width), focus[0] + focus[2] + REGION_PADDING)
    bottom = min(float(canvas.height), focus[1] + focus[3] + REGION_PADDING)
    if right - left < 8 or bottom - top < 8:
        return None
    region = canvas.crop((int(left), int(top), int(right), int(bottom)))
    scale = REGION_MAX_EDGE / max(float(region.width), float(region.height))
    if abs(scale - 1.0) > 0.01:
        region = region.resize(
            (max(1, round(region.width * scale)), max(1, round(region.height * scale))),
            Image.Resampling.BILINEAR,
        )
    buffer = io.BytesIO()
    region.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
def enrich_removal_previews(
    review: HifiRemovalReview,
    root: Path,
    inventory: FguiComponentInventory,
) -> HifiRemovalReview:
    """§9 disclosure: show the operator the old visual before remove/preserve."""
    if not review.groups:
        return review
    objects_by_id = {obj.object_id: obj for obj in inventory.objects}
    image_paths: dict[str, Path] | None = None
    cache: dict[Path, str] = {}
    used = 0
    groups: list[HifiRemovalGroup] = []
    for group in review.groups:
        members: list[HifiRemovalObject] = []
        for member in group.objects:
            source = objects_by_id.get(member.object_id)
            update: dict[str, object] = {}
            if source is not None:
                update["size"] = (source.width, source.height)
                if source.effective_text:
                    update["text"] = source.effective_text[:256]
                if (
                    source.object_type in {"image", "loader"}
                    and source.resource_id
                    and used < PREVIEW_OBJECT_LIMIT
                ):
                    if image_paths is None:
                        image_paths = _package_image_paths(root)
                    path = image_paths.get(source.resource_id)
                    if path is not None:
                        used += 1
                        update["preview_url"] = _preview_data_url(path, cache)
            if (
                not update.get("preview_url")
                and source is not None
                and source.component_relative_path
                and used < PREVIEW_OBJECT_LIMIT
            ):
                if image_paths is None:
                    image_paths = _package_image_paths(root)
                scale_x, scale_y = source.owner_scale
                local_x = (
                    (source.x - source.owner_origin[0]) / scale_x if scale_x else 0.0
                )
                local_y = (
                    (source.y - source.owner_origin[1]) / scale_y if scale_y else 0.0
                )
                region = _render_component_region(
                    root,
                    source.component_relative_path,
                    (
                        local_x,
                        local_y,
                        source.width / (scale_x or 1.0),
                        source.height / (scale_y or 1.0),
                    ),
                    image_paths,
                )
                if region is not None:
                    used += 1
                    update["preview_url"] = region
            members.append(member.model_copy(update=update) if update else member)
        groups.append(group.model_copy(update={"objects": tuple(members)}))
    return review.model_copy(update={"groups": tuple(groups)})


def _referenced_by_map(inventory: FguiComponentInventory) -> dict[str, tuple[str, ...]]:
    references: dict[str, list[str]] = {}
    for obj in inventory.objects:
        for target in obj.relation_refs:
            if target:
                references.setdefault(target, []).append(obj.object_id)
    return {key: tuple(dict.fromkeys(value)) for key, value in references.items()}


def _runtime_bound(obj: FguiObjectRef, referenced_by: tuple[str, ...]) -> bool:
    # §10 tier 1 is real runtime logic, not mere layout grouping. A plain
    # group_member carries behavior_protected, but deleting it only shrinks an
    # advanced group's bounds; it stays an ordinary visual. The genuine tier-1
    # signals are transition keyframes targeting the object, relations it owns
    # or that other objects pin to it, and exported instance parameters.
    # Gear/controller-driven visibility is tier 2 via controller_refs.
    return bool(
        obj.instance_parameters
        or obj.transition_refs
        or obj.relation_refs
        or referenced_by
    )


def _object_risk(obj: FguiObjectRef, referenced_by: tuple[str, ...]) -> int:
    # §10 ordering: runtime logic first, then controller/gear bindings,
    # independent components, visible visuals, plain legacy visuals.
    if _runtime_bound(obj, referenced_by):
        return _TIER_RUNTIME
    if obj.controller_refs:
        return _TIER_CONTROLLER
    if obj.object_type == "component":
        return _TIER_COMPONENT
    if obj.default_visible:
        return _TIER_VISIBLE
    return _TIER_PLAIN


def _reason(obj: FguiObjectRef, referenced_by: tuple[str, ...]) -> str:
    parts = ["PSD 目标态未找到对应内容，疑似被 UX 淘汰的旧视觉（§8 REMOVE_CANDIDATE）"]
    if referenced_by:
        parts.append("被关系引用：" + ", ".join(referenced_by[:4]))
    if obj.transition_refs:
        parts.append("被动画引用：" + ", ".join(obj.transition_refs[:4]))
    if obj.controller_refs:
        parts.append("控制器绑定：" + ", ".join(obj.controller_refs[:4]))
    return "；".join(parts)


def build_removal_review(
    mapping: HifiMappingDraft,
    inventory: FguiComponentInventory,
) -> HifiRemovalReview:
    """Group every undecided REMOVE_CANDIDATE into ≤ 5 user-facing groups."""
    candidates = [
        item for item in mapping.items
        if item.legacy_state == "REMOVE_CANDIDATE" and item.action is None
    ]
    if not candidates:
        return HifiRemovalReview(version=1)
    objects_by_id = {obj.object_id: obj for obj in inventory.objects}
    referenced = _referenced_by_map(inventory)
    grouped: dict[tuple[str, str], list[HifiRemovalObject]] = {}
    for item in candidates:
        obj = objects_by_id.get(item.old_object_id or "")
        if obj is None:
            continue
        refs = referenced.get(obj.object_id, ())
        semantic_root = (
            obj.component_relative_path
            or inventory.target.component_relative_path
        )
        # Instances of one shared template look identical but live in
        # different parents; presenting them as near-duplicate groups
        # confuses the operator. Merge them into one group whose single
        # decision covers every instance site.
        if obj.instance_path:
            local = obj.local_object_id or obj.object_id
            key = (semantic_root, "template:" + local)
            location = " › ".join((*obj.instance_path, local))
        else:
            key = (semantic_root, obj.parent_id or "")
            location = ""
        grouped.setdefault(key, []).append(HifiRemovalObject(
            version=1,
            item_id=item.item_id,
            object_id=obj.object_id,
            name=obj.name,
            object_type=obj.object_type,
            risk_tier=_object_risk(obj, refs),
            reason=_reason(obj, refs),
            controller_refs=obj.controller_refs,
            transition_refs=obj.transition_refs,
            relation_refs=obj.relation_refs,
            referenced_by=refs,
            runtime_bound=_runtime_bound(obj, refs),
            location=location,
        ))
    groups: list[HifiRemovalGroup] = []
    for (semantic_root, region_key), members in sorted(grouped.items()):
        tier = min(member.risk_tier for member in members)
        merged = region_key.startswith("template:")
        region = (
            f"共享模板 {region_key[9:]} · {len(members)} 处实例"
            if merged else region_key
        )
        group_id = "grp-" + hashlib.sha256(
            f"{semantic_root}\x00{region_key}".encode("utf-8")
        ).hexdigest()[:10]
        groups.append(HifiRemovalGroup(
            version=1,
            group_id=group_id,
            semantic_root=semantic_root,
            region=region,
            merged_template=merged,
            risk_tier=tier,
            # Runtime-bound groups are never recommended for silent removal;
            # preserving keeps the object addressable while §11 stops its
            # target-state visual contribution.
            recommendation="preserve" if tier <= _TIER_COMPONENT else "remove",
            objects=tuple(sorted(members, key=lambda m: m.object_id)),
        ))
    groups.sort(key=lambda group: (group.risk_tier, group.semantic_root, group.group_id))
    overflow = [
        group.model_copy(update={"auto_resolved": True})
        for group in groups[MAX_USER_FACING_GROUPS:]
    ]
    return HifiRemovalReview(
        version=1,
        pending=True,
        total_candidate_count=len(candidates),
        groups=tuple(groups[:MAX_USER_FACING_GROUPS]),
        auto_resolved_groups=tuple(overflow),
    )
