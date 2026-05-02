"""Tests for the AppleMusic HTTP client using httpx.MockTransport."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from applemusic import (
    AppleMusic,
    AppleMusicCredentials,
    AppleMusicError,
    AppleMusicHTTPError,
)


def make_client(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    storefront: str | None = None,
    **client_kwargs: Any,
) -> AppleMusic:
    """Build an AppleMusic whose HTTP transport is the given handler.

    Lets each test stub out responses without ever touching the network.
    Extra ``client_kwargs`` (e.g. ``max_retries=0``) are forwarded to
    ``AppleMusic.__init__``.
    """
    creds = AppleMusicCredentials(
        developer_token="fake.developer.jwt",
        media_user_token="fake-media-user-token",
        cookie_header="myacinfo=fake; media-user-token=fake-media-user-token",
    )
    client = AppleMusic(creds, storefront=storefront, **client_kwargs)
    client._http.close()
    client._http = httpx.Client(
        base_url="https://amp-api.music.apple.com",
        transport=httpx.MockTransport(handler),
        headers=client._build_headers(),
    )
    return client


# =========================================================================
# Read side
# =========================================================================


def test_request_headers_include_credentials() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={"data": [{"id": "ca", "type": "storefronts"}]},
        )

    client = make_client(handler)
    client.current_user_storefront()

    headers = captured[0].headers
    assert headers["authorization"] == "Bearer fake.developer.jwt"
    assert headers["media-user-token"] == "fake-media-user-token"
    assert "myacinfo=fake" in headers["cookie"]
    assert headers["accept"] == "application/json"


def test_search_resolves_storefront_then_searches() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if request.url.path == "/v1/me/storefront":
            return httpx.Response(
                200,
                json={"data": [{"id": "gb", "type": "storefronts"}]},
            )
        if request.url.path == "/v1/catalog/gb/search":
            return httpx.Response(
                200,
                json={"results": {"songs": {"data": [{"id": "1"}]}}},
            )
        return httpx.Response(404, json={})

    client = make_client(handler)
    results = client.search("queen", types=["songs", "artists"], limit=10)

    assert [r.url.path for r in captured] == [
        "/v1/me/storefront",
        "/v1/catalog/gb/search",
    ]
    query = dict(captured[1].url.params)
    assert query["term"] == "queen"
    assert query["types"] == "songs,artists"
    assert query["limit"] == "10"
    assert results == {"songs": {"data": [{"id": "1"}]}}


def test_search_uses_explicit_storefront_without_lookup() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"results": {}})

    client = make_client(handler, storefront="us")
    client.search("queen")

    assert len(captured) == 1
    assert captured[0].url.path == "/v1/catalog/us/search"


def test_paginate_walks_next_cursor() -> None:
    captured: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        full = str(request.url)
        captured.append(full)
        if "offset=2" in full:
            return httpx.Response(200, json={"data": [{"id": "3"}]})
        return httpx.Response(
            200,
            json={
                "data": [{"id": "1"}, {"id": "2"}],
                "next": "/v1/me/library/songs?offset=2",
            },
        )

    client = make_client(handler)
    songs = client.current_user_saved_tracks()

    assert [s["id"] for s in songs] == ["1", "2", "3"]
    assert len(captured) == 2


def test_http_error_raises_with_status_and_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text='{"errors":[{"detail":"forbidden"}]}')

    client = make_client(handler, storefront="us")
    with pytest.raises(AppleMusicHTTPError) as excinfo:
        client.search("queen")

    assert excinfo.value.status_code == 403
    assert "forbidden" in (excinfo.value.response_body or "")


def test_storefront_lookup_with_no_data_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    client = make_client(handler)
    with pytest.raises(AppleMusicError):
        client.current_user_storefront()


def test_catalog_album_includes_tracks_param() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={"data": [{"id": "12345", "type": "albums"}]},
        )

    client = make_client(handler, storefront="us")
    album = client.catalog_album("12345")

    assert captured[0].url.path == "/v1/catalog/us/albums/12345"
    assert dict(captured[0].url.params).get("include") == "tracks"
    assert album["id"] == "12345"


def test_catalog_artist_not_found_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    client = make_client(handler, storefront="us")
    with pytest.raises(AppleMusicError) as excinfo:
        client.catalog_artist("99999")
    assert "99999" in str(excinfo.value)


def test_catalog_songs_by_isrc_packs_filter_param() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "1", "type": "songs", "attributes": {"isrc": "USRC11700001"}},
                    {"id": "2", "type": "songs", "attributes": {"isrc": "USRC11700002"}},
                ]
            },
        )

    client = make_client(handler, storefront="us")
    songs = client.catalog_songs_by_isrc(["USRC11700001", "USRC11700002"])

    assert captured[0].method == "GET"
    assert captured[0].url.path == "/v1/catalog/us/songs"
    assert dict(captured[0].url.params)["filter[isrc]"] == "USRC11700001,USRC11700002"
    assert [s["id"] for s in songs] == ["1", "2"]


def test_catalog_songs_by_isrc_empty_match_returns_empty_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    client = make_client(handler, storefront="us")
    assert client.catalog_songs_by_isrc(["XXNON00000000"]) == []


def test_catalog_songs_by_isrc_empty_input_raises() -> None:
    client = make_client(lambda r: httpx.Response(500), storefront="us")
    with pytest.raises(ValueError):
        client.catalog_songs_by_isrc([])


def test_catalog_albums_by_upc_packs_filter_param() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "100", "type": "albums", "attributes": {"upc": "060253766935"}},
                ]
            },
        )

    client = make_client(handler, storefront="us")
    albums = client.catalog_albums_by_upc(["060253766935", "060253766942"])

    assert captured[0].url.path == "/v1/catalog/us/albums"
    assert dict(captured[0].url.params)["filter[upc]"] == "060253766935,060253766942"
    assert [a["id"] for a in albums] == ["100"]


def test_catalog_albums_by_upc_empty_input_raises() -> None:
    client = make_client(lambda r: httpx.Response(500), storefront="us")
    with pytest.raises(ValueError):
        client.catalog_albums_by_upc([])


def test_catalog_filter_resolves_storefront_when_unset() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if request.url.path == "/v1/me/storefront":
            return httpx.Response(
                200,
                json={"data": [{"id": "ca", "type": "storefronts"}]},
            )
        return httpx.Response(200, json={"data": []})

    client = make_client(handler)
    client.catalog_songs_by_isrc(["USRC11700001"])

    assert [r.url.path for r in captured] == [
        "/v1/me/storefront",
        "/v1/catalog/ca/songs",
    ]


def test_library_playlist_fetches_single_envelope() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "p.X",
                        "type": "library-playlists",
                        "attributes": {"name": "My Playlist"},
                    }
                ]
            },
        )

    client = make_client(handler, storefront="us")
    playlist = client.library_playlist("p.X")

    assert captured[0].method == "GET"
    assert captured[0].url.path == "/v1/me/library/playlists/p.X"
    assert playlist["id"] == "p.X"
    assert playlist["attributes"]["name"] == "My Playlist"


def test_library_song_not_found_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    client = make_client(handler, storefront="us")
    with pytest.raises(AppleMusicError) as excinfo:
        client.library_song("i.missing")
    assert "i.missing" in str(excinfo.value)


# =========================================================================
# Library mutations
# =========================================================================


def test_playlist_create_with_description_and_tracks() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            201,
            json={
                "data": [
                    {
                        "id": "p.YYY",
                        "type": "library-playlists",
                        "attributes": {"name": "Test"},
                    }
                ]
            },
        )

    client = make_client(handler, storefront="us")
    result = client.playlist_create(
        "Test",
        description="Test description",
        track_ids=["1234567890", "9876543210"],
    )

    assert captured[0].method == "POST"
    assert captured[0].url.path == "/v1/me/library/playlists"
    body = json.loads(captured[0].content)
    assert body["attributes"]["name"] == "Test"
    assert body["attributes"]["description"] == "Test description"
    assert body["relationships"]["tracks"]["data"] == [
        {"id": "1234567890", "type": "songs"},
        {"id": "9876543210", "type": "songs"},
    ]
    assert result["id"] == "p.YYY"


def test_playlist_create_minimal_omits_relationships() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            201,
            json={"data": [{"id": "p.X", "type": "library-playlists"}]},
        )

    client = make_client(handler, storefront="us")
    client.playlist_create("Just a name")

    body = json.loads(captured[0].content)
    assert body == {"attributes": {"name": "Just a name"}}


def test_playlist_update_sends_attributes_only() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={"data": [{"id": "p.ABC", "attributes": {"name": "Renamed"}}]},
        )

    client = make_client(handler, storefront="us")
    result = client.playlist_update("p.ABC", name="Renamed")

    assert captured[0].method == "PATCH"
    assert captured[0].url.path == "/v1/me/library/playlists/p.ABC"
    body = json.loads(captured[0].content)
    assert body == {"attributes": {"name": "Renamed"}}
    assert result["id"] == "p.ABC"


def test_playlist_update_handles_204_no_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(204)

    client = make_client(handler, storefront="us")
    result = client.playlist_update("p.ABC", description="Updated")
    assert result == {}


def test_playlist_update_with_no_changes_raises() -> None:
    client = make_client(lambda r: httpx.Response(500), storefront="us")
    with pytest.raises(ValueError):
        client.playlist_update("p.X")


def test_playlist_delete() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(204)

    client = make_client(handler, storefront="us")
    client.playlist_delete("p.ABC123")

    assert captured[0].method == "DELETE"
    assert captured[0].url.path == "/v1/me/library/playlists/p.ABC123"


def test_playlist_add_tracks_uses_specified_kind() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(204)

    client = make_client(handler, storefront="us")
    client.playlist_add_tracks(
        "p.ABC",
        ["i.aaa", "i.bbb"],
        track_kind="library-songs",
    )

    assert captured[0].method == "POST"
    assert captured[0].url.path == "/v1/me/library/playlists/p.ABC/tracks"
    body = json.loads(captured[0].content)
    assert body == {
        "data": [
            {"id": "i.aaa", "type": "library-songs"},
            {"id": "i.bbb", "type": "library-songs"},
        ]
    }


def test_playlist_add_tracks_empty_raises() -> None:
    client = make_client(lambda r: httpx.Response(500), storefront="us")
    with pytest.raises(ValueError):
        client.playlist_add_tracks("p.ABC", [])


def test_playlist_remove_track() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(204)

    client = make_client(handler, storefront="us")
    client.playlist_remove_track("p.ABC", "i.xyz")

    assert captured[0].method == "DELETE"
    assert captured[0].url.path == "/v1/me/library/playlists/p.ABC/tracks/i.xyz"


def test_library_add_packs_ids_per_kind() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(202)

    client = make_client(handler, storefront="us")
    client.library_add(songs=["1", "2"], albums=["3"], music_videos=["4"])

    assert captured[0].method == "POST"
    assert captured[0].url.path == "/v1/me/library"
    params = dict(captured[0].url.params)
    assert params["ids[songs]"] == "1,2"
    assert params["ids[albums]"] == "3"
    assert params["ids[music-videos]"] == "4"


def test_library_add_with_nothing_raises() -> None:
    client = make_client(lambda r: httpx.Response(500), storefront="us")
    with pytest.raises(ValueError):
        client.library_add()


def test_library_remove_song_and_album() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(204)

    client = make_client(handler, storefront="us")
    client.library_remove_song("i.song")
    client.library_remove_album("l.album")

    assert captured[0].method == "DELETE"
    assert captured[0].url.path == "/v1/me/library/songs/i.song"
    assert captured[1].method == "DELETE"
    assert captured[1].url.path == "/v1/me/library/albums/l.album"


# =========================================================================
# Retry / backoff
# =========================================================================


def test_no_retry_on_2xx() -> None:
    call_count = [0]

    def handler(request: httpx.Request) -> httpx.Response:
        call_count[0] += 1
        return httpx.Response(200, json={"data": [{"id": "ok"}]})

    client = make_client(handler, storefront="us")
    client.search("queen")

    assert call_count[0] == 1


def test_retries_on_429_honours_retry_after(monkeypatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr("applemusic.client.time.sleep", lambda s: sleeps.append(s))

    call_count = [0]

    def handler(request: httpx.Request) -> httpx.Response:
        call_count[0] += 1
        if call_count[0] == 1:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return httpx.Response(200, json={"results": {}})

    client = make_client(handler, storefront="us")
    client.search("queen")

    assert call_count[0] == 2
    assert sleeps == [2.0]


def test_retries_on_500_with_exponential_backoff(monkeypatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr("applemusic.client.time.sleep", lambda s: sleeps.append(s))
    # Pin random.uniform to its upper bound so backoff numbers are deterministic.
    monkeypatch.setattr("applemusic.client.random.uniform", lambda lo, hi: hi)

    statuses = [500, 502, 200]
    call_count = [0]

    def handler(request: httpx.Request) -> httpx.Response:
        call_count[0] += 1
        status = statuses.pop(0)
        if status == 200:
            return httpx.Response(200, json={"results": {}})
        return httpx.Response(status)

    client = make_client(handler, storefront="us", retry_backoff=1.0)
    client.search("queen")

    # Two retries → two sleeps with exponential backoff:
    #   attempt 0: 1.0 * 2^0 = 1.0
    #   attempt 1: 1.0 * 2^1 = 2.0
    assert sleeps == [1.0, 2.0]
    assert call_count[0] == 3


def test_retries_on_connect_error_then_succeeds(monkeypatch) -> None:
    monkeypatch.setattr("applemusic.client.time.sleep", lambda s: None)

    call_count = [0]

    def handler(request: httpx.Request) -> httpx.Response:
        call_count[0] += 1
        if call_count[0] == 1:
            raise httpx.ConnectError("simulated network blip")
        return httpx.Response(200, json={"results": {}})

    client = make_client(handler, storefront="us")
    client.search("queen")

    assert call_count[0] == 2


def test_does_not_retry_on_403() -> None:
    call_count = [0]

    def handler(request: httpx.Request) -> httpx.Response:
        call_count[0] += 1
        return httpx.Response(403, text="forbidden")

    client = make_client(handler, storefront="us")
    with pytest.raises(AppleMusicHTTPError):
        client.search("queen")

    assert call_count[0] == 1


def test_exhausts_retries_then_raises_with_final_status(monkeypatch) -> None:
    monkeypatch.setattr("applemusic.client.time.sleep", lambda s: None)

    call_count = [0]

    def handler(request: httpx.Request) -> httpx.Response:
        call_count[0] += 1
        return httpx.Response(503, text="overloaded")

    client = make_client(handler, storefront="us", max_retries=3)
    with pytest.raises(AppleMusicHTTPError) as excinfo:
        client.search("queen")

    assert call_count[0] == 4  # 1 initial + 3 retries
    assert excinfo.value.status_code == 503
    assert "overloaded" in (excinfo.value.response_body or "")


def test_max_retries_zero_means_one_attempt() -> None:
    call_count = [0]

    def handler(request: httpx.Request) -> httpx.Response:
        call_count[0] += 1
        return httpx.Response(503)

    client = make_client(handler, storefront="us", max_retries=0)
    with pytest.raises(AppleMusicHTTPError) as excinfo:
        client.search("queen")

    assert call_count[0] == 1
    assert excinfo.value.status_code == 503


def test_retry_after_clamped_to_backoff_max(monkeypatch) -> None:
    """A huge Retry-After (e.g. 600s) must be capped at retry_backoff_max."""
    sleeps: list[float] = []
    monkeypatch.setattr("applemusic.client.time.sleep", lambda s: sleeps.append(s))

    call_count = [0]

    def handler(request: httpx.Request) -> httpx.Response:
        call_count[0] += 1
        if call_count[0] == 1:
            return httpx.Response(429, headers={"Retry-After": "600"})
        return httpx.Response(200, json={"results": {}})

    client = make_client(handler, storefront="us", retry_backoff_max=10.0)
    client.search("queen")

    assert sleeps == [10.0]


def test_network_error_exhausts_retries(monkeypatch) -> None:
    monkeypatch.setattr("applemusic.client.time.sleep", lambda s: None)

    call_count = [0]

    def handler(request: httpx.Request) -> httpx.Response:
        call_count[0] += 1
        raise httpx.ConnectError("never works")

    client = make_client(handler, storefront="us", max_retries=2)
    with pytest.raises(AppleMusicHTTPError) as excinfo:
        client.search("queen")

    assert call_count[0] == 3  # 1 initial + 2 retries
    assert "never works" in str(excinfo.value)
