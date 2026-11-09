"""Cloudflare R2 adapter. R2 speaks the S3 API, so boto3 is pointed at the account endpoint.

Credentials are passed in from settings and never logged. Errors are reduced to a
safe message with no endpoint, key or credential in it.
"""

import asyncio
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.storage.objects import PDF_CONTENT_TYPE, ObjectNotFound, ObjectStoreError, sha256_hex, validate_key

MISSING_CODES = frozenset({"NoSuchKey", "404", "NotFound"})


def build_r2_client(account_id: str, access_key_id: str, secret_access_key: str) -> Any:
    return boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name="auto",
    )


class R2ObjectStore:
    def __init__(self, client: Any, bucket: str):
        if not bucket:
            raise ObjectStoreError("bucket is not configured")
        self._client = client
        self._bucket = bucket

    async def put_pdf(self, key: str, data: bytes) -> str:
        validate_key(key)
        if not data:
            raise ObjectStoreError("refusing to store an empty file")
        digest = sha256_hex(data)
        try:
            await asyncio.to_thread(
                self._client.put_object,
                Bucket=self._bucket,
                Key=key,
                Body=data,
                ContentType=PDF_CONTENT_TYPE,
                Metadata={"sha256": digest},
            )
        except (ClientError, BotoCoreError) as exc:
            raise ObjectStoreError("file could not be stored") from exc
        return digest

    async def get_pdf(self, key: str) -> bytes:
        validate_key(key)
        try:
            response = await asyncio.to_thread(self._client.get_object, Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in MISSING_CODES:
                raise ObjectNotFound("file not found") from exc
            raise ObjectStoreError("file could not be read") from exc
        except BotoCoreError as exc:
            raise ObjectStoreError("file could not be read") from exc
        return await asyncio.to_thread(response["Body"].read)

    async def delete(self, key: str) -> None:
        validate_key(key)
        try:
            await asyncio.to_thread(self._client.delete_object, Bucket=self._bucket, Key=key)
        except (ClientError, BotoCoreError) as exc:
            raise ObjectStoreError("file could not be deleted") from exc
