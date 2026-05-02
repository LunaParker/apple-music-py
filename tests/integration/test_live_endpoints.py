"""Live integration tests against amp-api.music.apple.com.

These tests skip unless ``AppleMusicAuth().load_cached()`` returns valid
credentials. To run them, authenticate once first::

    python examples/login_and_dump.py
    pytest tests/integration

The mutation tests create temporary playlists named with an
``applemusic-py integration test`` prefix and clean them up at the end of
each test, so running the suite leaves no junk behind in the user's
library — assuming nothing crashes mid-test, in which case the orphaned
playlist can be deleted manually.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from applemusic import (
    AppleMusic,
    AppleMusicAuth,
    AppleMusicCredentials,
)

PLAYLIST_PREFIX = "applemusic-py integration test"


@pytest.fixture(scope="module")
def credentials() -> AppleMusicCredentials:
    auth = AppleMusicAuth()
    creds = auth.load_cached()
    if creds is None:
        pytest.skip(
            "No cached Apple Music credentials. Run "
            "`python examples/login_and_dump.py` once to authenticate."
        )
    return creds


@pytest.fixture(scope="module")
def client(credentials: AppleMusicCredentials) -> Iterator[AppleMusic]:
    with AppleMusic(credentials) as c:
        yield c


# =========================================================================
# Read side
# =========================================================================


def test_storefront_lookup(client: AppleMusic) -> None:
    storefront = client.current_user_storefront()
    assert storefront["type"] == "storefronts"
    assert isinstance(storefront["id"], str)
    assert storefront["id"]  # non-empty


def test_search_artists(client: AppleMusic) -> None:
    results = client.search("Queen", types=["artists"], limit=5)
    artists = results.get("artists", {}).get("data", [])
    assert len(artists) > 0
    assert all(a["type"] == "artists" for a in artists)


def test_search_songs(client: AppleMusic) -> None:
    results = client.search("Bohemian Rhapsody", types=["songs"], limit=5)
    songs = results.get("songs", {}).get("data", [])
    assert len(songs) > 0
    assert all(s["type"] == "songs" for s in songs)


def test_search_albums(client: AppleMusic) -> None:
    results = client.search("A Night at the Opera", types=["albums"], limit=5)
    albums = results.get("albums", {}).get("data", [])
    assert len(albums) > 0
    assert all(a["type"] == "albums" for a in albums)


def test_search_multi_type(client: AppleMusic) -> None:
    results = client.search(
        "Queen",
        types=["songs", "albums", "artists"],
        limit=3,
    )
    assert "songs" in results
    assert "albums" in results
    assert "artists" in results


def test_current_user_saved_tracks_returns_list(client: AppleMusic) -> None:
    tracks = client.current_user_saved_tracks()
    assert isinstance(tracks, list)
    # Library may be empty for a fresh account — don't assert non-empty


def test_current_user_saved_albums_returns_list(client: AppleMusic) -> None:
    albums = client.current_user_saved_albums()
    assert isinstance(albums, list)


def test_current_user_saved_artists_returns_list(client: AppleMusic) -> None:
    artists = client.current_user_saved_artists()
    assert isinstance(artists, list)


def test_current_user_playlists_returns_list(client: AppleMusic) -> None:
    playlists = client.current_user_playlists()
    assert isinstance(playlists, list)


def test_catalog_artist_round_trip(client: AppleMusic) -> None:
    """Search then look up the same artist by catalog ID."""
    search = client.search("Queen", types=["artists"], limit=1)
    artists = search.get("artists", {}).get("data", [])
    assert len(artists) > 0

    artist_id = artists[0]["id"]
    artist = client.catalog_artist(artist_id)
    assert artist["id"] == artist_id
    assert artist["type"] == "artists"


def test_catalog_album_round_trip(client: AppleMusic) -> None:
    """Search then look up the same album by catalog ID; album includes tracks."""
    search = client.search("A Night at the Opera Queen", types=["albums"], limit=1)
    albums = search.get("albums", {}).get("data", [])
    assert len(albums) > 0

    album_id = albums[0]["id"]
    album = client.catalog_album(album_id)
    assert album["id"] == album_id
    assert album["type"] == "albums"
    # include=tracks should populate the relationships
    tracks_rel = album.get("relationships", {}).get("tracks", {})
    assert "data" in tracks_rel


# =========================================================================
# Mutation lifecycle
# =========================================================================


def test_playlist_create_and_delete(client: AppleMusic) -> None:
    """Bare-minimum mutation cycle: create an empty playlist, then delete it.

    Verification uses ``library_playlist(id)`` directly rather than scanning
    ``current_user_playlists()``, because Apple's library listing endpoint is
    eventually consistent — newly-created playlists may take several seconds
    to appear in the list, but a direct fetch by ID succeeds immediately.
    """
    playlist = client.playlist_create(f"{PLAYLIST_PREFIX} (create+delete)")
    playlist_id = playlist["id"]
    assert playlist_id
    assert playlist["type"] in ("library-playlists", "playlists")

    try:
        fetched = client.library_playlist(playlist_id)
        assert fetched["id"] == playlist_id
        assert PLAYLIST_PREFIX in fetched["attributes"]["name"]
    finally:
        client.playlist_delete(playlist_id)


def test_playlist_lifecycle_with_tracks(client: AppleMusic) -> None:
    """Create → add a song → list tracks → delete cycle."""
    playlist = client.playlist_create(
        f"{PLAYLIST_PREFIX} (with tracks)",
        description="Created by applemusic-py integration tests; safe to delete.",
    )
    playlist_id = playlist["id"]

    try:
        results = client.search(
            "Queen Bohemian Rhapsody",
            types=["songs"],
            limit=1,
        )
        songs = results.get("songs", {}).get("data", [])
        assert len(songs) > 0, "Could not find a catalog song to add"
        song_id = songs[0]["id"]

        client.playlist_add_tracks(playlist_id, [song_id])

        tracks = client.playlist_tracks(playlist_id)
        assert len(tracks) > 0, "Added track did not appear in playlist"
    finally:
        client.playlist_delete(playlist_id)


def test_playlist_rename_via_update(client: AppleMusic) -> None:
    """Create → rename via playlist_update → verify via direct fetch → delete."""
    initial = f"{PLAYLIST_PREFIX} (initial name)"
    renamed = f"{PLAYLIST_PREFIX} (renamed)"

    playlist = client.playlist_create(initial)
    playlist_id = playlist["id"]

    try:
        client.playlist_update(playlist_id, name=renamed)

        fetched = client.library_playlist(playlist_id)
        assert fetched["attributes"]["name"] == renamed
    finally:
        client.playlist_delete(playlist_id)
