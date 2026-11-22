"""Chunking settings: valid values are accepted, and values that would make the worker loop forever are refused."""

import asyncio

import pytest
from pydantic import ValidationError

from app.ai.chunking import PageText, chunk_pages
from app.config import Settings


def test_default_chunking_settings_are_valid():
    settings = Settings(chunk_max_chars=1000, chunk_overlap_chars=150)
    assert settings.chunk_overlap_chars < settings.chunk_max_chars


@pytest.mark.parametrize("max_chars, overlap", [
    (1000, 1000),   # overlap equal to the chunk size: no progress
    (1000, 1500),   # overlap larger than the chunk size
    (0, 0),         # no chunk size at all
    (1000, -1),     # negative overlap
])
def test_invalid_chunking_settings_are_refused_at_startup(max_chars, overlap):
    with pytest.raises(ValidationError):
        Settings(chunk_max_chars=max_chars, chunk_overlap_chars=overlap)


def test_the_chunker_refuses_a_non_advancing_window_instead_of_looping():
    async def run():
        return chunk_pages([PageText(page_number=1, text="x" * 5000)], 100, 100)

    with pytest.raises(ValueError):
        asyncio.run(asyncio.wait_for(run(), timeout=2))
