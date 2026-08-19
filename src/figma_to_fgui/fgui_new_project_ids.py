"""Deterministic target identities and safe generated-project paths.

The Writer v1 ID policy intentionally uses a fixed eight-character lowercase
hexadecimal SHA-256 prefix.  This is a writer policy, not an inferred
extension of FairyGUI's observed ID formats.  A prefix collision is therefore
an error rather than a reason to add entropy or widen an ID at runtime.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable
from pathlib import PurePosixPath

TARGET_ID_WIDTH = 8
MAX_TARGET_PATH_SEGMENT_UTF16 = 255

_KIND = re.compile(r"^[a-z][a-z0-9_-]*$")
_TARGET_ID = re.compile(rf"^[0-9a-f]{{{TARGET_ID_WIDTH}}}$")
_WINDOWS_RESERVED_BASENAMES = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{number}" for number in range(1, 10)),
        *(f"lpt{number}" for number in range(1, 10)),
        *(f"com{number}" for number in "¹²³"),
        *(f"lpt{number}" for number in "¹²³"),
    }
)
_WINDOWS_FORBIDDEN_CHARACTERS = frozenset('<>:"/\\|?*')
_RESOURCE_SUFFIXES = frozenset({".png", ".jpg", ".webp"})

Request = tuple[str, str]
CollisionGroup = tuple[Request, ...]


class TargetNamingError(ValueError):
    """A user-facing target name or its safe comparison key is invalid."""


class TargetIdCollisionError(ValueError):
    """Two distinct allocation requests share the fixed Writer v1 ID prefix."""

    def __init__(self, collisions: tuple[CollisionGroup, ...]) -> None:
        self.collisions = collisions
        super().__init__("deterministic target ID collision")


def _contains_control_character(value: str) -> bool:
    return any(unicodedata.category(character).startswith("C") for character in value)


def _comparison_key(value: str) -> str:
    """Use NFC and casefold only when comparing names; never rewrite output."""
    return unicodedata.normalize("NFC", value).casefold()


def _utf16_code_units(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def _require_segment_length(value: str) -> str:
    if _utf16_code_units(value) > MAX_TARGET_PATH_SEGMENT_UTF16:
        raise TargetNamingError("target path segment is too long")
    return value


def _validated_path_segment(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or _contains_control_character(value)
        or any(character in _WINDOWS_FORBIDDEN_CHARACTERS for character in value)
        or value.endswith((".", " "))
    ):
        raise TargetNamingError("invalid target path segment")

    normalized = unicodedata.normalize("NFC", value)
    basename = normalized.split(".", maxsplit=1)[0].casefold()
    if basename in _WINDOWS_RESERVED_BASENAMES:
        raise TargetNamingError("invalid reserved target path segment")
    return _require_segment_length(value)


def _validated_kind(kind: str) -> str:
    if not isinstance(kind, str) or _KIND.fullmatch(kind) is None:
        raise TargetNamingError("invalid target kind")
    return kind


def _validated_logical_key(logical_key: str) -> str:
    if (
        not isinstance(logical_key, str)
        or not logical_key
        or _contains_control_character(logical_key)
    ):
        raise TargetNamingError("invalid target logical key")
    return logical_key


def validate_target_name(value: str, kind: str) -> str:
    """Validate one visible name without changing the spelling supplied by the user."""
    _validated_kind(kind)
    return _validated_path_segment(value)


def id_digest(kind: str, logical_key: str) -> str:
    """Return the canonical, full SHA-256 digest for one target request."""
    return hashlib.sha256(f"{kind}:{logical_key}".encode()).hexdigest()


def _request_from(value: object) -> Request:
    if not isinstance(value, tuple) or len(value) != 2:
        raise TargetNamingError("invalid target ID request")
    kind, logical_key = value
    return _validated_kind(kind), _validated_logical_key(logical_key)


def _require_distinct_comparison_keys(requests: Iterable[Request]) -> None:
    seen: dict[tuple[str, str], str] = {}
    for kind, logical_key in sorted(requests):
        key = (kind, _comparison_key(logical_key))
        previous = seen.setdefault(key, logical_key)
        if previous != logical_key:
            raise TargetNamingError("case-insensitive target logical key collision")


class TargetIdAllocator:
    """Allocate fixed-width IDs and fail closed for every ambiguous namespace."""

    def __init__(self) -> None:
        self._assigned: dict[Request, str] = {}

    def allocate(self, kind: str, logical_key: str) -> str:
        """Allocate one request while retaining collision checks for later requests."""
        request = (_validated_kind(kind), _validated_logical_key(logical_key))
        return self.allocate_all((request,))[request]

    def allocate_all(self, requests: Iterable[tuple[str, str]]) -> dict[Request, str]:
        """Allocate an order-independent set of requests atomically.

        The returned mapping is sorted by request identity.  Existing requests are
        included so subsequent single-request allocation cannot bypass a collision.
        """
        incoming = {_request_from(request) for request in requests}
        all_requests = set(self._assigned) | incoming
        _require_distinct_comparison_keys(all_requests)

        assigned = {
            request: id_digest(*request)[:TARGET_ID_WIDTH] for request in sorted(all_requests)
        }
        reverse: dict[str, list[Request]] = defaultdict(list)
        for request in sorted(assigned):
            reverse[assigned[request]].append(request)
        collisions = tuple(
            tuple(reverse[target_id])
            for target_id in sorted(reverse)
            if len(reverse[target_id]) > 1
        )
        if collisions:
            raise TargetIdCollisionError(collisions)

        self._assigned = assigned
        return dict(assigned)


def _validated_target_id(target_id: str) -> str:
    if not isinstance(target_id, str) or _TARGET_ID.fullmatch(target_id) is None:
        raise TargetNamingError("invalid deterministic target ID")
    return target_id


def _validated_suffix(suffix: str) -> str:
    if not isinstance(suffix, str) or suffix not in _RESOURCE_SUFFIXES:
        raise TargetNamingError("invalid resource suffix")
    return suffix


def validate_unique_target_paths(paths: Iterable[PurePosixPath]) -> tuple[PurePosixPath, ...]:
    """Reject duplicate target paths under the Windows NFC/casefold comparison rule.

    Generated projects target Unity on Windows in Writer v1, so paths compare
    per segment after NFC/casefold.  Exact duplicates are rejected too: a
    manifest cannot safely declare two files for one destination.
    """
    validated: list[PurePosixPath] = []
    seen: set[tuple[str, ...]] = set()
    for path in paths:
        if not isinstance(path, PurePosixPath) or path.is_absolute() or not path.parts:
            raise TargetNamingError("invalid target path")
        for segment in path.parts:
            _validated_path_segment(segment)
        comparison_path = tuple(_comparison_key(segment) for segment in path.parts)
        if comparison_path in seen:
            raise TargetNamingError("target path collision")
        seen.add(comparison_path)
        validated.append(path)
    return tuple(validated)


def component_path(name: str, target_id: str) -> PurePosixPath:
    """Return a portable, readable component XML path within one package."""
    readable_name = validate_target_name(name, "component")
    stable_id = _validated_target_id(target_id)
    filename = _require_segment_length(f"{readable_name}-{stable_id}.xml")
    return validate_unique_target_paths((PurePosixPath("components", filename),))[0]


def resource_path(name: str, target_id: str, suffix: str) -> PurePosixPath:
    """Return a portable, readable resource path within one package."""
    readable_name = validate_target_name(name, "resource")
    stable_id = _validated_target_id(target_id)
    extension = _validated_suffix(suffix)
    filename = _require_segment_length(f"{readable_name}-{stable_id}{extension}")
    return validate_unique_target_paths((PurePosixPath("resources", filename),))[0]
