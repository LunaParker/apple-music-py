"""Tests for the AppleMusic HTTP client using httpx.MockTransport."""

from __future__ import annotations

from collections.abc import Callable

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
) -> AppleMusic:
    """Build an AppleMusic whose HTTP transport is the given handler.

    Lets each test stub out responses without ever touching the network.
    """
    creds = AppleMusicCredentials(
        developer_token="fake.developer.jwt",
        media_user_token="fake-media-user-token",
        cookie_header="myacinfo=fake; media-user-token=fake-media-user-token",
    )
    client = AppleMusic(creds, storefront=storefront)
    client._http.close()
    client._http = httpx.Client(
        base_url="https://amp-api.music.apple.com",
        transport=httpx.MockTransport(handler),
        headers=client._build_headers(),
    )
    return client


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
