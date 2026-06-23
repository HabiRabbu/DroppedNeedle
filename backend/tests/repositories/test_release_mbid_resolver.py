"""Tests for MusicBrainzIdResolver (release MBID -> release-group MBID)."""

from unittest.mock import AsyncMock

import pytest

from repositories.musicbrainz_id_resolver import MusicBrainzIdResolver


@pytest.mark.asyncio
async def test_resolve_delegates_to_repo():
    repo = AsyncMock()
    repo.get_release_group_id_from_release = AsyncMock(return_value="rg-123")
    resolver = MusicBrainzIdResolver(repo)

    result = await resolver.resolve_release_to_release_group("rel-abc")

    assert result == "rg-123"
    repo.get_release_group_id_from_release.assert_awaited_once_with("rel-abc")


@pytest.mark.asyncio
async def test_resolve_empty_input_short_circuits():
    repo = AsyncMock()
    repo.get_release_group_id_from_release = AsyncMock()
    resolver = MusicBrainzIdResolver(repo)

    assert await resolver.resolve_release_to_release_group("") is None
    repo.get_release_group_id_from_release.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolve_returns_none_when_repo_finds_nothing():
    repo = AsyncMock()
    repo.get_release_group_id_from_release = AsyncMock(return_value=None)
    resolver = MusicBrainzIdResolver(repo)

    assert await resolver.resolve_release_to_release_group("rel-x") is None
