"""Private filesystem object storage for local development demos only."""

import asyncio
import os
import tempfile
from pathlib import Path

from app.storage.objects import ObjectNotFound, ObjectStoreError, sha256_hex, validate_key


class LocalObjectStore:
    """Store PDFs beneath a private local directory; use R2 for hosted deployments."""

    def __init__(self, directory: str | Path):
        if not str(directory).strip():
            raise ObjectStoreError("local storage directory is not configured")
        self._root = Path(directory).expanduser().resolve()

    def _path(self, key: str) -> Path:
        validate_key(key)
        path = (self._root / key).resolve()
        if not path.is_relative_to(self._root):
            raise ObjectStoreError("invalid object key")
        return path

    async def put_pdf(self, key: str, data: bytes) -> str:
        path = self._path(key)
        if not data:
            raise ObjectStoreError("refusing to store an empty file")
        return await asyncio.to_thread(self._put, path, data)

    def _put(self, path: Path, data: bytes) -> str:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".upload-", delete=False) as temp:
                temp_path = Path(temp.name)
                temp.write(data)
                temp.flush()
                os.fsync(temp.fileno())
            os.chmod(temp_path, 0o600)
            os.replace(temp_path, path)
        except OSError as exc:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            raise ObjectStoreError("file could not be stored") from exc
        return sha256_hex(data)

    async def get_pdf(self, key: str) -> bytes:
        path = self._path(key)
        try:
            return await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError as exc:
            raise ObjectNotFound("file not found") from exc
        except OSError as exc:
            raise ObjectStoreError("file could not be read") from exc

    async def delete(self, key: str) -> None:
        path = self._path(key)
        try:
            await asyncio.to_thread(path.unlink, missing_ok=True)
        except OSError as exc:
            raise ObjectStoreError("file could not be deleted") from exc
