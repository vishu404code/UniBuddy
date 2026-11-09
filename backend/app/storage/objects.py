"""Object storage for uploaded PDFs. The interface is shared by the R2 adapter and the test fake.

Keys are fixed to `<campus UUID>/<document UUID>.pdf`, which is how uploads are stored. A
key that doesn't match is refused, so no caller can write outside that layout.
"""

import hashlib
import re
from typing import Protocol

_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
KEY_PATTERN = re.compile(rf"{_UUID}/{_UUID}\.pdf")
PDF_CONTENT_TYPE = "application/pdf"


class ObjectStoreError(Exception):
    """A storage request was refused or failed. The message holds no secrets."""


class ObjectNotFound(ObjectStoreError):
    pass


def validate_key(key: str) -> None:
    if not isinstance(key, str) or not KEY_PATTERN.fullmatch(key):
        raise ObjectStoreError("invalid object key")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ObjectStore(Protocol):
    async def put_pdf(self, key: str, data: bytes) -> str:
        """Stores the bytes and returns their SHA-256 hex digest."""

    async def get_pdf(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...
