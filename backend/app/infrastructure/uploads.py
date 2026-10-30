import hashlib
import re
from pathlib import Path

from app.config import get_settings


def _root() -> Path:
    return Path(get_settings().upload_dir).resolve()


def safe_filename(filename: str) -> str:
    name = Path(filename).name
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "upload"
    return cleaned[:120]


def save_upload(seller_id: str, document_id: str, filename: str, data: bytes) -> tuple[str, str]:
    """Store the original bytes; returns (storage path relative to the upload root, sha256)."""
    relative = Path(seller_id) / f"{document_id}_{safe_filename(filename)}"
    target = _root() / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return relative.as_posix(), hashlib.sha256(data).hexdigest()


def read_upload(relative_path: str) -> bytes:
    root = _root()
    target = (root / relative_path).resolve()
    if root not in target.parents:
        raise ValueError("upload path escapes the upload root")
    return target.read_bytes()
