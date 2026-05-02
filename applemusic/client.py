"""High-level client for the Apple Music web API.

Methods are spotipy-shaped: short verb-noun names that map to user library
and catalog endpoints. Each returns parsed JSON; pagination is handled
internally so callers get the full list back without having to follow
``next``-cursor URLs themselves.
"""

from __future__ import annotations

from collections.abc import Iterator
from types import TracebackType
from typing import Any

import httpx

from applemusic.auth import AMP_API_BASE, AppleMusicCredentials
from applemusic.exceptions import AppleMusicError, AppleMusicHTTPError
from applemusic.pagination import paginate


class AppleMusic:
    """Authenticated client for ``amp-api.music.apple.com``.

    Construct with credentials returned by
    :meth:`applemusic.AppleMusicAuth.authenticate`::

        auth = AppleMusicAuth()
        client = AppleMusic(auth.authenticate())
        for song in client.current_user_saved_tracks():
            print(song["attributes"]["name"])

    Use as a context manager (or call :meth:`close`) to release the
    underlying HTTP connection pool.
    """

    PAGE_SIZE = 100

    def __init__(
        self,
        credentials: AppleMusicCredentials,
        *,
        storefront: str | None = None,
        language: str = "en-US",
        timeout: float = 30.0,
    ) -> None:
        self._credentials = credentials
        self._language = language
        self._storefront = storefront
        self._http = httpx.Client(
            base_url=AMP_API_BASE,
            timeout=timeout,
            headers=self._build_headers(),
        )

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._http.close()

    def __enter__(self) -> AppleMusic:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def _build_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._credentials.developer_token}",
            "media-user-token": self._credentials.media_user_token,
            "Cookie": self._credentials.cookie_header,
            "Origin": "https://music.apple.com",
            "Referer": "https://music.apple.com/",
            "Accept": "application/json",
            "Accept-Language": self._language,
        }

    # --------------------------------------------------------------- internal

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        response = self._http.request(method, path, params=params, json=json)
        if response.status_code >= 400:
            raise AppleMusicHTTPError(
                f"{method} {path} returned HTTP {response.status_code}",
                status_code=response.status_code,
                response_body=response.text,
            )
        return response

    def _get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request("GET", path, params=params).json()

    def _ensure_storefront(self) -> str:
        if self._storefront is None:
            self._storefront = _extract_storefront_id(self._get("/v1/me/storefront"))
        return self._storefront

    def _library_iter(self, path: str) -> Iterator[dict[str, Any]]:
        return paginate(
            self._get,
            path,
            {"l": self._language, "limit": self.PAGE_SIZE},
        )

    # ------------------------------------------------------------------ user

    def current_user_storefront(self) -> dict[str, Any]:
        """Return the user's storefront record (e.g. ``us``, ``ca``, ``gb``).

        The response includes the storefront identifier plus its display name
        and the languages that storefront supports.
        """
        envelope = self._get("/v1/me/storefront")
        data = envelope.get("data") or []
        if not data:
            raise AppleMusicError("Apple Music did not return a storefront for this user")
        return data[0]

    def current_user_saved_tracks(self) -> list[dict[str, Any]]:
        """Return every song in the user's library."""
        return list(self._library_iter("/v1/me/library/songs"))

    def current_user_saved_albums(self) -> list[dict[str, Any]]:
        """Return every album in the user's library."""
        return list(self._library_iter("/v1/me/library/albums"))

    def current_user_saved_artists(self) -> list[dict[str, Any]]:
        """Return every artist in the user's library."""
        return list(self._library_iter("/v1/me/library/artists"))

    def current_user_playlists(self) -> list[dict[str, Any]]:
        """Return every playlist in the user's library."""
        return list(self._library_iter("/v1/me/library/playlists"))

    def playlist_tracks(self, playlist_id: str) -> list[dict[str, Any]]:
        """Return the tracks in the given library playlist."""
        return list(self._library_iter(f"/v1/me/library/playlists/{playlist_id}/tracks"))

    # --------------------------------------------------------------- catalog

    def search(
        self,
        query: str,
        *,
        types: list[str] | None = None,
        limit: int = 25,
    ) -> dict[str, Any]:
        """Search the Apple Music catalog.

        ``types`` defaults to ``["songs"]``; pass any combination of
        ``songs``, ``albums``, ``artists``, ``music-videos``, ``playlists``,
        or ``stations``. Returns the raw ``results`` envelope keyed by type.
        """
        storefront = self._ensure_storefront()
        params: dict[str, Any] = {
            "term": query,
            "types": ",".join(types or ["songs"]),
            "limit": str(limit),
            "l": self._language,
        }
        envelope = self._get(f"/v1/catalog/{storefront}/search", params)
        return envelope.get("results", {})

    def catalog_song(self, song_id: str) -> dict[str, Any]:
        """Return a song from the Apple Music catalog by ID."""
        return self._catalog_one("songs", song_id)

    def catalog_album(self, album_id: str) -> dict[str, Any]:
        """Return an album (with its tracks) from the Apple Music catalog by ID."""
        return self._catalog_one("albums", album_id, include="tracks")

    def catalog_artist(self, artist_id: str) -> dict[str, Any]:
        """Return an artist from the Apple Music catalog by ID."""
        return self._catalog_one("artists", artist_id)

    def catalog_playlist(self, playlist_id: str) -> dict[str, Any]:
        """Return a public/curated playlist from the Apple Music catalog by ID."""
        return self._catalog_one("playlists", playlist_id, include="tracks")

    def _catalog_one(
        self,
        kind: str,
        item_id: str,
        *,
        include: str | None = None,
    ) -> dict[str, Any]:
        storefront = self._ensure_storefront()
        params: dict[str, Any] = {"l": self._language}
        if include is not None:
            params["include"] = include
        envelope = self._get(f"/v1/catalog/{storefront}/{kind}/{item_id}", params)
        data = envelope.get("data") or []
        if not data:
            raise AppleMusicError(f"Apple Music catalog has no {kind[:-1]} with id {item_id}")
        return data[0]


def _extract_storefront_id(envelope: dict[str, Any]) -> str:
    data = envelope.get("data") or []
    if not data:
        raise AppleMusicError("Apple Music did not return a storefront for this user")
    storefront_id = data[0].get("id")
    if not storefront_id:
        raise AppleMusicError("Apple Music storefront response is missing 'id'")
    return storefront_id
