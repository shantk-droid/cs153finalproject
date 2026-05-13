"""Disk-backed temp storage for raw uploads between /datasets/upload and /datasets/{id}/confirm.

Also: per-dataset metadata sidecar JSON (`{data_path}/metadata/{dataset_id}.json`),
which carries the profile selection and audit fields. Reading is fault-tolerant —
a missing file resolves to the legacy default (`retail_m5`) so existing datasets
keep working without backfill.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from apps.api.config import get_settings


@dataclass(frozen=True)
class StoredUpload:
    dataset_id: str
    filename: str
    sheet_override: str | None
    file_path: Path
    meta_path: Path


class DatasetMetadata(BaseModel):
    dataset_id: str
    profile_id: str
    profile_auto_detected: bool = False
    match_confidence: float | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def _uploads_dir() -> Path:
    base = get_settings().data_path.parent / "uploads"
    base.mkdir(parents=True, exist_ok=True)
    return base


def save_upload(dataset_id: str, filename: str, content: bytes, sheet_override: str | None = None) -> StoredUpload:
    uploads = _uploads_dir()
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else "bin"
    file_path = uploads / f"{dataset_id}.{ext}"
    file_path.write_bytes(content)
    meta_path = uploads / f"{dataset_id}.meta.json"
    meta_path.write_text(json.dumps({"filename": filename, "sheet_override": sheet_override}))
    return StoredUpload(dataset_id=dataset_id, filename=filename, sheet_override=sheet_override,
                        file_path=file_path, meta_path=meta_path)


def load_upload(dataset_id: str) -> StoredUpload:
    uploads = _uploads_dir()
    meta_path = uploads / f"{dataset_id}.meta.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"upload {dataset_id} not found")
    meta = json.loads(meta_path.read_text())
    candidates = list(uploads.glob(f"{dataset_id}.*"))
    file_path = next((p for p in candidates if not p.name.endswith(".meta.json")), None)
    if file_path is None:
        raise FileNotFoundError(f"upload file for {dataset_id} not found")
    return StoredUpload(dataset_id=dataset_id, filename=meta["filename"],
                        sheet_override=meta.get("sheet_override"),
                        file_path=file_path, meta_path=meta_path)


def cleanup_upload(dataset_id: str) -> None:
    """Delete the raw upload after a successful confirm. Idempotent."""
    uploads = _uploads_dir()
    for p in uploads.glob(f"{dataset_id}.*"):
        p.unlink(missing_ok=True)


def _metadata_dir() -> Path:
    base = get_settings().data_path / "metadata"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _metadata_path(dataset_id: str) -> Path:
    return _metadata_dir() / f"{dataset_id}.json"


def read_dataset_metadata(dataset_id: str) -> DatasetMetadata:
    """Return the dataset's metadata. Falls back to a synthetic retail_m5 record if missing."""
    p = _metadata_path(dataset_id)
    if p.exists():
        return DatasetMetadata.model_validate_json(p.read_text())
    return DatasetMetadata(dataset_id=dataset_id, profile_id="retail_m5")


def write_dataset_metadata(meta: DatasetMetadata) -> None:
    _metadata_path(meta.dataset_id).write_text(meta.model_dump_json(indent=2))
