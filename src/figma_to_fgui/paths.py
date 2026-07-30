from pathlib import PurePosixPath


def safe_relative_path(value: str) -> str:
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if not path.parts or path.is_absolute() or ":" in path.parts[0] or ".." in path.parts:
        raise ValueError(f"unsafe relative path: {value}")
    return path.as_posix()
