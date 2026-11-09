"""Stage 1 storage: key rules, the in-memory fake, and the R2 adapter.

The R2 adapter is tested with botocore's Stubber, which answers before any request
leaves the machine. These tests make no network calls and need no R2 account.
"""

from uuid import uuid4

import boto3
import pytest
from botocore.stub import Stubber

from app.storage.objects import ObjectNotFound, ObjectStoreError, sha256_hex, validate_key
from app.storage.r2 import R2ObjectStore

CAMPUS = uuid4()
DOC = uuid4()
KEY = f"{CAMPUS}/{DOC}.pdf"
PDF = b"%PDF-1.4 synthetic test bytes"


class MemoryStore:
    """Test fake with the same contract as R2ObjectStore."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}

    async def put_pdf(self, key, data):
        validate_key(key)
        if not data:
            raise ObjectStoreError("refusing to store an empty file")
        self.objects[key] = data
        return sha256_hex(data)

    async def get_pdf(self, key):
        validate_key(key)
        if key not in self.objects:
            raise ObjectNotFound("file not found")
        return self.objects[key]

    async def delete(self, key):
        validate_key(key)
        self.objects.pop(key, None)


def _client():
    return boto3.client(
        "s3",
        endpoint_url="https://test-account.r2.cloudflarestorage.com",
        aws_access_key_id="synthetic-access-key",
        aws_secret_access_key="synthetic-secret",
        region_name="auto",
    )


# --- Keys ------------------------------------------------------------------------------

def test_upload_key_layout_is_accepted():
    validate_key(KEY)


@pytest.mark.parametrize(
    "key",
    [
        "../" + KEY,
        f"{CAMPUS}/../{DOC}.pdf",
        f"{CAMPUS}/{DOC}.pdf/extra",
        f"{CAMPUS}/{DOC}.txt",
        f"{CAMPUS}/{str(DOC).upper()}.pdf",
        f"/{KEY}",
        f"{CAMPUS}/{DOC}.PDF",
        "",
        None,
    ],
)
def test_other_keys_are_refused(key):
    with pytest.raises(ObjectStoreError):
        validate_key(key)


# --- In-memory fake --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fake_round_trip_returns_the_same_bytes_and_digest():
    store = MemoryStore()

    digest = await store.put_pdf(KEY, PDF)

    assert digest == sha256_hex(PDF)
    assert await store.get_pdf(KEY) == PDF


@pytest.mark.asyncio
async def test_fake_missing_and_deleted_files_are_not_found():
    store = MemoryStore()
    await store.put_pdf(KEY, PDF)
    await store.delete(KEY)

    with pytest.raises(ObjectNotFound):
        await store.get_pdf(KEY)


@pytest.mark.asyncio
async def test_empty_upload_is_refused():
    with pytest.raises(ObjectStoreError):
        await MemoryStore().put_pdf(KEY, b"")


# --- R2 adapter (Stubber, no network) --------------------------------------------------

@pytest.mark.asyncio
async def test_r2_put_sends_the_key_content_type_and_checksum_metadata():
    client = _client()
    store = R2ObjectStore(client, bucket="unibuddy-documents")
    with Stubber(client) as stub:
        stub.add_response(
            "put_object",
            {"ETag": '"x"'},
            {
                "Bucket": "unibuddy-documents",
                "Key": KEY,
                "Body": PDF,
                "ContentType": "application/pdf",
                "Metadata": {"sha256": sha256_hex(PDF)},
            },
        )

        digest = await store.put_pdf(KEY, PDF)
        stub.assert_no_pending_responses()

    assert digest == sha256_hex(PDF)


@pytest.mark.asyncio
async def test_r2_get_returns_the_stored_bytes():
    client = _client()
    store = R2ObjectStore(client, bucket="unibuddy-documents")
    with Stubber(client) as stub:
        stub.add_response(
            "get_object",
            {"Body": _Body(PDF)},
            {"Bucket": "unibuddy-documents", "Key": KEY},
        )

        assert await store.get_pdf(KEY) == PDF


@pytest.mark.asyncio
async def test_r2_missing_object_becomes_not_found_without_detail():
    client = _client()
    store = R2ObjectStore(client, bucket="unibuddy-documents")
    with Stubber(client) as stub:
        stub.add_client_error(
            "get_object",
            service_error_code="NoSuchKey",
            service_message="The specified key does not exist.",
            http_status_code=404,
            expected_params={"Bucket": "unibuddy-documents", "Key": KEY},
        )

        with pytest.raises(ObjectNotFound) as info:
            await store.get_pdf(KEY)

    assert "unibuddy" not in str(info.value)
    assert KEY not in str(info.value)


@pytest.mark.asyncio
async def test_r2_access_errors_are_reduced_to_a_safe_message():
    client = _client()
    store = R2ObjectStore(client, bucket="unibuddy-documents")
    with Stubber(client) as stub:
        stub.add_client_error(
            "delete_object",
            service_error_code="AccessDenied",
            service_message="secret-token-in-message",
            http_status_code=403,
            expected_params={"Bucket": "unibuddy-documents", "Key": KEY},
        )

        with pytest.raises(ObjectStoreError) as info:
            await store.delete(KEY)

    assert str(info.value) == "file could not be deleted"


def test_r2_adapter_refuses_an_empty_bucket_name():
    with pytest.raises(ObjectStoreError):
        R2ObjectStore(_client(), bucket="")


@pytest.mark.asyncio
async def test_r2_adapter_refuses_bad_keys_before_any_request():
    client = _client()
    store = R2ObjectStore(client, bucket="unibuddy-documents")
    with Stubber(client):  # no responses queued: any request would fail the test
        with pytest.raises(ObjectStoreError):
            await store.put_pdf("../escape.pdf", PDF)


class _Body:
    def __init__(self, data: bytes):
        self._data = data

    def read(self) -> bytes:
        return self._data
