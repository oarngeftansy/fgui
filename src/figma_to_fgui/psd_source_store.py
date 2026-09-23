from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from figma_to_fgui.psd_intake import PsdAnalysis, PsdInspection, PsdLayer, analyze_psd


class PsdSourceStoreError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class PsdSource:
    version: int
    source_id: str
    inspection: PsdInspection
    layers: tuple[PsdLayer, ...]


class PsdSourceStore:
    def __init__(self, data_dir: Path) -> None:
        self._root = data_dir / "hifi-sources" / "psd"
        self._root.mkdir(parents=True, exist_ok=True)

    def admit(self, upload_path: Path, *, source_name: str) -> PsdSource:
        analysis = analyze_psd(upload_path, source_name=source_name)
        source_id = analysis.inspection.sha256
        destination = self._root / source_id
        if destination.is_dir():
            upload_path.unlink(missing_ok=True)
            return self.get(source_id)

        staging = self._root / f".admit-{source_id}-{uuid.uuid4().hex}"
        staging.mkdir()
        try:
            upload_path.replace(staging / "source.psd")
            payload = self._payload(source_id, analysis)
            (staging / "hifi-ir.json").write_text(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            try:
                staging.rename(destination)
            except OSError:
                if not destination.is_dir():
                    raise
                shutil.rmtree(staging)
            return self.get(source_id)
        except Exception:
            if staging.exists():
                shutil.rmtree(staging)
            raise

    def get(self, source_id: str) -> PsdSource:
        if len(source_id) != 64 or any(character not in "0123456789abcdef" for character in source_id):
            raise PsdSourceStoreError("psd_source_not_found")
        source_root = self._root / source_id
        source_path = source_root / "source.psd"
        manifest_path = source_root / "hifi-ir.json"
        if not source_path.is_file() or not manifest_path.is_file():
            raise PsdSourceStoreError("psd_source_not_found")
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            source = self._parse(payload, expected_source_id=source_id)
            if source_path.stat().st_size != source.inspection.byte_size:
                raise PsdSourceStoreError("psd_source_corrupt")
            digest = sha256()
            with source_path.open("rb") as stored_psd:
                while chunk := stored_psd.read(1024 * 1024):
                    digest.update(chunk)
            if digest.hexdigest() != source_id:
                raise PsdSourceStoreError("psd_source_corrupt")
            return source
        except PsdSourceStoreError:
            raise
        except (OSError, TypeError, ValueError, KeyError) as error:
            raise PsdSourceStoreError("psd_source_corrupt") from error

    @staticmethod
    def _payload(source_id: str, analysis: PsdAnalysis) -> dict[str, Any]:
        return {
            "version": 1,
            "source_id": source_id,
            "inspection": asdict(analysis.inspection),
            "layers": [asdict(layer) for layer in analysis.layers],
        }

    @staticmethod
    def payload(source: PsdSource) -> dict[str, Any]:
        return {
            "version": source.version,
            "source_id": source.source_id,
            "inspection": asdict(source.inspection),
            "layers": [asdict(layer) for layer in source.layers],
        }

    @staticmethod
    def _parse(payload: Any, *, expected_source_id: str) -> PsdSource:
        if not isinstance(payload, dict) or payload.get("version") != 1:
            raise PsdSourceStoreError("psd_source_corrupt")
        if payload.get("source_id") != expected_source_id:
            raise PsdSourceStoreError("psd_source_corrupt")
        inspection_data = payload.get("inspection")
        layers_data = payload.get("layers")
        if not isinstance(inspection_data, dict) or not isinstance(layers_data, list):
            raise PsdSourceStoreError("psd_source_corrupt")
        inspection = PsdInspection(
            **{
                **inspection_data,
                "blocking_issues": tuple(inspection_data["blocking_issues"]),
                "warnings": tuple(inspection_data["warnings"]),
            }
        )
        if inspection.sha256 != expected_source_id:
            raise PsdSourceStoreError("psd_source_corrupt")
        layers = tuple(
            PsdLayer(
                **{
                    **item,
                    "path": tuple(item["path"]),
                    "bounds": tuple(item["bounds"]),
                }
            )
            for item in layers_data
            if isinstance(item, dict)
        )
        if len(layers) != len(layers_data) or len(layers) != inspection.layer_count:
            raise PsdSourceStoreError("psd_source_corrupt")
        if len({layer.id for layer in layers}) != len(layers):
            raise PsdSourceStoreError("psd_source_corrupt")
        return PsdSource(version=1, source_id=expected_source_id, inspection=inspection, layers=layers)
