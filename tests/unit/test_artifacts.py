from __future__ import annotations

import base64
import hashlib
from pathlib import Path

import pytest

from figma_to_fgui.artifacts import ArtifactIntegrityError, ArtifactStore
from figma_to_fgui.service_contracts import ChangeBundle, ChangeFile, FileOperation


def make_bundle() -> ChangeBundle:
    payload = b"<component/>"
    return ChangeBundle(
        job_id="job-1",
        project_id="project-1",
        files=(
            ChangeFile(
                operation=FileOperation.CREATE,
                relative_path="Sample/Main.xml",
                after_sha256=hashlib.sha256(payload).hexdigest(),
                content_b64=base64.b64encode(payload).decode("ascii"),
            ),
        ),
    )


def test_artifact_store_round_trips_by_content_hash(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    bundle = make_bundle()
    digest = store.put(bundle)
    assert len(digest) == 64
    assert store.get(digest) == bundle
    assert list(tmp_path.iterdir()) == [tmp_path / f"{digest}.json"]


def test_artifact_store_detects_tampering(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    digest = store.put(make_bundle())
    (tmp_path / f"{digest}.json").write_text("{}", "utf-8")
    with pytest.raises(ArtifactIntegrityError):
        store.get(digest)


@pytest.mark.parametrize("digest", ["../escape", "not-a-hash", "a" * 63])
def test_artifact_store_rejects_invalid_digest(tmp_path: Path, digest: str) -> None:
    with pytest.raises(ArtifactIntegrityError):
        ArtifactStore(tmp_path).get(digest)
