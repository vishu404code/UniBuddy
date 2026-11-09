"""S3-compatible private storage (for example Neon Object Storage). No network: botocore's Stubber
checks each request's parameters and returns canned responses."""

import asyncio
import io
from uuid import uuid4

import pytest
from botocore.stub import Stubber

from app.config import settings
from app.services import providers
from app.storage.objects import ObjectNotFound, sha256_hex
from app.storage.r2 import R2ObjectStore, build_s3_client

ENDPOINT = "https://s3.example.test"


def _client():
    return build_s3_client(ENDPOINT, "us-east-1", "AKIATESTONLY", "test-secret-not-real")


def test_client_uses_path_style_sigv4_and_the_configured_endpoint():
    client = _client()
    assert client.meta.endpoint_url == ENDPOINT
    assert client.meta.config.s3["addressing_style"] == "path"
    assert client.meta.config.signature_version == "s3v4"
    assert client.meta.region_name == "us-east-1"


def test_put_and_get_send_the_expected_bucket_key_and_digest():
    client = _client()
    store = R2ObjectStore(client, "unibuddy-documents")
    key = f"{uuid4()}/{uuid4()}.pdf"
    data = b"%PDF-1.4 synthetic test bytes"
    digest = sha256_hex(data)

    with Stubber(client) as stub:
        stub.add_response("put_object", {"ETag": '"x"'}, {
            "Bucket": "unibuddy-documents", "Key": key, "Body": data,
            "ContentType": "application/pdf", "Metadata": {"sha256": digest},
        })
        stub.add_response("get_object", {"Body": io.BytesIO(data)}, {
            "Bucket": "unibuddy-documents", "Key": key,
        })
        assert asyncio.run(store.put_pdf(key, data)) == digest
        assert asyncio.run(store.get_pdf(key)) == data
        stub.assert_no_pending_responses()


def test_missing_object_is_reported_as_not_found():
    client = _client()
    store = R2ObjectStore(client, "unibuddy-documents")
    key = f"{uuid4()}/{uuid4()}.pdf"
    with Stubber(client) as stub:
        stub.add_client_error("get_object", service_error_code="NoSuchKey",
                              expected_params={"Bucket": "unibuddy-documents", "Key": key})
        with pytest.raises(ObjectNotFound):
            asyncio.run(store.get_pdf(key))


def test_s3_backend_is_selected_only_when_all_settings_are_present(monkeypatch):
    monkeypatch.setattr(settings, "storage_backend", "s3")
    monkeypatch.setattr(settings, "s3_endpoint_url", None)
    monkeypatch.setattr(settings, "s3_access_key_id", "k")
    monkeypatch.setattr(settings, "s3_secret_access_key", "s")
    assert providers._storage_configured() is False
    with pytest.raises(RuntimeError, match="S3 storage is not configured"):
        providers.build_object_store()

    monkeypatch.setattr(settings, "s3_endpoint_url", ENDPOINT)
    assert providers._storage_configured() is True
    store = providers.build_object_store()
    assert isinstance(store, R2ObjectStore)


def test_s3_backend_is_allowed_in_production(monkeypatch):
    monkeypatch.setattr(settings, "storage_backend", "s3")
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "s3_endpoint_url", ENDPOINT)
    monkeypatch.setattr(settings, "s3_access_key_id", "k")
    monkeypatch.setattr(settings, "s3_secret_access_key", "s")
    assert providers._storage_configured() is True
