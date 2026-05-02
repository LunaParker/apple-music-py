"""High-level client for the Apple Music web API.

Methods are spotipy-shaped: short verb-noun names that map to user library
and catalog endpoints. Each returns parsed JSON; pagination is handled
internally so callers get the full list back without having to follow
``next``-cursor URLs themselves.
"""

from __future__ import annotations

import random
import time
from collections.abc import Iterator
from types import TracebackType
from typing import Any

import httpx

from applemusic.auth import AMP_API_BASE, AppleMusicCredentials
from applemusic.exceptions import AppleMusicError, AppleMusicHTTPError
from applemusic.pagination import paginate

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


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
        max_retries: int = 3,
        retry_backoff: float = 1.0,
        retry_backoff_max: float = 30.0,
    ) -> None:
        self._credentials = credentials
        self._language = language
        self._storefront = storefront
        self._max_retries = max_retries
        self._retry_backoff = retry_backoff
        self._retry_backoff_max = retry_backoff_max
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
        last_network_error: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                response = self._http.request(
                    method, path, params=params, json=json
                )
            except (
                httpx.TimeoutException,
                httpx.NetworkError,
                httpx.RemoteProtocolError,
            ) as e:
                last_network_error = e
                if attempt < self._max_retries:
                    time.sleep(self._retry_delay(attempt))
                    continue
                raise AppleMusicHTTPError(
                    f"{method} {path} failed after {attempt + 1} attempts: {e}",
                    status_code=0,
                    response_body=None,
                ) from e

            if (
                response.status_code in RETRYABLE_STATUS
                and attempt < self._max_retries
            ):
                time.sleep(self._delay_for_response(response, attempt))
                continue

            if response.status_code >= 400:
                raise AppleMusicHTTPError(
                    f"{method} {path} returned HTTP {response.status_code}",
                    status_code=response.status_code,
                    response_body=response.text,
                )
            return response

        # Defensive — every loop branch above either continues or returns/raises.
        raise AppleMusicHTTPError(
            f"{method} {path} exhausted retries unexpectedly",
            status_code=0,
            response_body=str(last_network_error) if last_network_error else None,
        )

    def _retry_delay(self, attempt: int) -> float:
        """Exponential backoff with full jitter, capped at ``retry_backoff_max``."""
        ceiling = min(
            self._retry_backoff * (2**attempt),
            self._retry_backoff_max,
        )
        return random.uniform(0.0, ceiling)

    def _delay_for_response(self, response: httpx.Response, attempt: int) -> float:
        """Honour ``Retry-After`` on a retryable response; fall back to backoff."""
        retry_after = response.headers.get("Retry-After", "").strip()
        if retry_after:
            try:
                seconds = float(retry_after)
            except ValueError:
                # HTTP-date format — Apple amp-api uses integer seconds, so this
                # is rare; fall through to exponential backoff.
                pass
            else:
                return min(max(seconds, 0.0), self._retry_backoff_max)
        return self._retry_delay(attempt)

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

    def library_song(self, song_id: str) -> dict[str, Any]:
        """Return a single song from the user's library by its library-song ID."""
        return self._library_one("songs", song_id)

    def library_album(self, album_id: str) -> dict[str, Any]:
        """Return a single album from the user's library by its library-album ID."""
        return self._library_one("albums", album_id)

    def library_artist(self, artist_id: str) -> dict[str, Any]:
        """Return a single artist from the user's library by its library-artist ID."""
        return self._library_one("artists", artist_id)

    def library_playlist(self, playlist_id: str) -> dict[str, Any]:
        """Return a single playlist from the user's library by its library-playlist ID.

        Useful for verifying a just-created playlist exists:
        ``current_user_playlists`` has eventual consistency on Apple's side, so
        newly-created playlists may take several seconds to appear in the
        listing, but a direct fetch by ID succeeds immediately.
        """
        return self._library_one("playlists", playlist_id)

    def _library_one(self, kind: str, item_id: str) -> dict[str, Any]:
        envelope = self._get(
            f"/v1/me/library/{kind}/{item_id}",
            {"l": self._language},
        )
        data = envelope.get("data") or []
        if not data:
            raise AppleMusicError(f"Library has no {kind[:-1]} with id {item_id}")
        return data[0]

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

    # ------------------------------------------------------- library mutations

    def playlist_create(
        self,
        name: str,
        *,
        description: str | None = None,
        track_ids: list[str] | None = None,
        track_kind: str = "songs",
    ) -> dict[str, Any]:
        """Create a new playlist in the user's library.

        ``track_kind`` is the JSON:API ``type`` field for entries in
        ``track_ids``: use ``"songs"`` for catalog tracks (the usual case)
        or ``"library-songs"`` for tracks already saved in the library.
        Returns the new playlist envelope (containing the assigned id).
        """
        attributes: dict[str, Any] = {"name": name}
        if description is not None:
            attributes["description"] = description

        body: dict[str, Any] = {"attributes": attributes}
        if track_ids:
            body["relationships"] = {
                "tracks": {
                    "data": [{"id": tid, "type": track_kind} for tid in track_ids],
                }
            }

        envelope = self._request("POST", "/v1/me/library/playlists", json=body).json()
        data = envelope.get("data") or []
        if not data:
            raise AppleMusicError("Playlist create response had no `data` array")
        return data[0]

    def playlist_update(
        self,
        playlist_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Rename or re-describe an existing library playlist.

        Returns the updated playlist envelope, or an empty dict if the API
        responds 204 No Content (some Apple endpoints do).
        """
        attributes: dict[str, Any] = {}
        if name is not None:
            attributes["name"] = name
        if description is not None:
            attributes["description"] = description
        if not attributes:
            raise ValueError("playlist_update needs at least one of `name=` or `description=`")

        body = {"attributes": attributes}
        response = self._request(
            "PATCH",
            f"/v1/me/library/playlists/{playlist_id}",
            json=body,
        )
        if response.status_code == 204 or not response.content:
            return {}
        envelope = response.json()
        data = envelope.get("data") or []
        return data[0] if data else {}

    def playlist_delete(self, playlist_id: str) -> None:
        """Delete a playlist from the user's library."""
        self._request("DELETE", f"/v1/me/library/playlists/{playlist_id}")

    def playlist_add_tracks(
        self,
        playlist_id: str,
        track_ids: list[str],
        *,
        track_kind: str = "songs",
    ) -> None:
        """Append tracks to an existing library playlist.

        ``track_kind`` is the JSON:API ``type`` field — see
        :meth:`playlist_create` for guidance on which value to pass.
        """
        if not track_ids:
            raise ValueError("playlist_add_tracks needs at least one track id")
        body = {"data": [{"id": tid, "type": track_kind} for tid in track_ids]}
        self._request(
            "POST",
            f"/v1/me/library/playlists/{playlist_id}/tracks",
            json=body,
        )

    def playlist_remove_track(self, playlist_id: str, track_id: str) -> None:
        """Remove a single track from a library playlist by its library-song ID."""
        self._request(
            "DELETE",
            f"/v1/me/library/playlists/{playlist_id}/tracks/{track_id}",
        )

    def library_add(
        self,
        *,
        songs: list[str] | None = None,
        albums: list[str] | None = None,
        artists: list[str] | None = None,
        music_videos: list[str] | None = None,
    ) -> None:
        """Add catalog items to the user's library.

        Pass any combination of ID lists; at least one kind must be supplied.
        Catalog IDs (not library IDs) are expected — Apple converts them on
        ingest.
        """
        params: dict[str, Any] = {}
        if songs:
            params["ids[songs]"] = ",".join(songs)
        if albums:
            params["ids[albums]"] = ",".join(albums)
        if artists:
            params["ids[artists]"] = ",".join(artists)
        if music_videos:
            params["ids[music-videos]"] = ",".join(music_videos)
        if not params:
            raise ValueError("library_add needs at least one non-empty kind")
        self._request("POST", "/v1/me/library", params=params)

    def library_remove_song(self, song_id: str) -> None:
        """Remove a song from the user's library by its library-song ID."""
        self._request("DELETE", f"/v1/me/library/songs/{song_id}")

    def library_remove_album(self, album_id: str) -> None:
        """Remove an album from the user's library by its library-album ID."""
        self._request("DELETE", f"/v1/me/library/albums/{album_id}")


def _extract_storefront_id(envelope: dict[str, Any]) -> str:
    data = envelope.get("data") or []
    if not data:
        raise AppleMusicError("Apple Music did not return a storefront for this user")
    storefront_id = data[0].get("id")
    if not storefront_id:
        raise AppleMusicError("Apple Music storefront response is missing 'id'")
    return storefront_id
