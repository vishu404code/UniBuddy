from uuid import uuid4

import pytest

from app.storage.local import LocalObjectStore
from app.storage.objects import ObjectNotFound, ObjectStoreError, sha256_hex


@pytest.mark.asyncio
async def test_local_storage_round_trip_and_digest(tmp_path):
    store = LocalObjectStore(tmp_path)
    key = f"{uuid4()}/{uuid4()}.pdf"
    data = b"%PDF-1.4 local demo"

    digest = await store.put_pdf(key, data)

    assert digest == sha256_hex(data)
    assert await store.get_pdf(key) == data


@pytest.mark.asyncio
async def test_local_storage_missing_and_deleted_files(tmp_path):
    store = LocalObjectStore(tmp_path)
    key = f"{uuid4()}/{uuid4()}.pdf"
    with pytest.raises(ObjectNotFound):
        await store.get_pdf(key)
    await store.put_pdf(key, b"pdf")
    await store.delete(key)
    with pytest.raises(ObjectNotFound):
        await store.get_pdf(key)


@pytest.mark.asyncio
async def test_local_storage_rejects_bad_keys_and_empty_files(tmp_path):
    store = LocalObjectStore(tmp_path)
    with pytest.raises(ObjectStoreError):
        await store.put_pdf("../outside.pdf", b"pdf")
    with pytest.raises(ObjectStoreError):
        await store.put_pdf(f"{uuid4()}/{uuid4()}.pdf", b"")


def test_local_storage_requires_a_directory():
    with pytest.raises(ObjectStoreError):
        LocalObjectStore("")


def test_local_storage_is_refused_in_production(monkeypatch):
    from app.config import settings
    from app.services import providers

    monkeypatch.setattr(settings, "storage_backend", "local")
    monkeypatch.setattr(settings, "app_env", "production")

    import pytest as _pytest

    with _pytest.raises(RuntimeError, match="laptop demos only"):
        providers.build_object_store()
    assert providers._storage_configured() is False
