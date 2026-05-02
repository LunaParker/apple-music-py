"""High-level client for the Apple Music web API.

Methods are spotipy-shaped: short verb-noun names that map to user library
and catalog endpoints. Each returns parsed JSON; pagination is handled
internally so callers get the full list back without having to follow
``next``-cursor URLs themselves.

Implementation is pending; this module currently defines the public surface
and request-header construction only.
"""

from __future__ import annotations

from types import TracebackType
from typing import Any

import httpx

from applemusic.auth import AMP_API_BASE, AppleMusicCredentials


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

    # ------------------------------------------------------------------ user

    def current_user_storefront(self) -> dict[str, Any]:
        """Return the user's storefront record (e.g. ``us``, ``ca``, ``gb``)."""
        raise NotImplementedError

    def current_user_saved_tracks(self) -> list[dict[str, Any]]:
        """Return every song in the user's library."""
        raise NotImplementedError

    def current_user_playlists(self) -> list[dict[str, Any]]:
        """Return every playlist in the user's library."""
        raise NotImplementedError

    def playlist_tracks(self, playlist_id: str) -> list[dict[str, Any]]:
        """Return the tracks in the given library playlist."""
        raise NotImplementedError

    # --------------------------------------------------------------- catalog

    def search(
        self,
        query: str,
        *,
        types: list[str] | None = None,
        limit: int = 25,
    ) -> dict[str, Any]:
        """Search the Apple Music catalog.

        ``types`` defaults to ``["songs"]``. Pass any combination of
        ``songs``, ``albums``, ``artists``, ``playlists``, etc.
        """
        raise NotImplementedError
