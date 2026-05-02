"""Browser-driven authentication for Apple Music.

Spawns a headed Chromium via Playwright, lets the user complete sign-in
(including 2FA) on their own timeline, then captures the developer JWT, the
per-user ``media-user-token``, and the session cookie jar so subsequent
requests to ``amp-api.music.apple.com`` succeed without further interaction.

Implementation is pending; this module currently defines the public surface
and persistence layout only.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DEFAULT_SESSION_DIR = Path.home() / ".cache" / "applemusic"

APPLE_MUSIC_HOME = "https://music.apple.com"
AMP_API_BASE = "https://amp-api.music.apple.com"


@dataclass(frozen=True)
class AppleMusicCredentials:
    """The three values needed to authenticate against amp-api.music.apple.com.

    All three are scraped from a real signed-in music.apple.com session — see
    :class:`AppleMusicAuth` for the capture flow.
    """

    developer_token: str
    """JWT signed by Apple and embedded in the music.apple.com web client.

    Rotates roughly every six months; can be re-scraped silently from a fresh
    page load with no user interaction.
    """

    media_user_token: str
    """Per-user identifier set as a cookie after a successful sign-in.

    Persists until Apple expires the user's session cookies.
    """

    cookie_header: str
    """The full ``Cookie`` header string from the signed-in session.

    Includes ``media-user-token`` plus account-level cookies such as
    ``myacinfo``; sent verbatim on every request to ``amp-api``.
    """


class AppleMusicAuth:
    """Browser-driven authentication manager for Apple Music.

    Typical usage::

        auth = AppleMusicAuth()
        credentials = auth.authenticate()   # opens Chromium; user signs in
        client = AppleMusic(credentials)

    The flow opens a headed Chromium window, lets the user complete sign-in at
    their own pace (Apple's 2FA can take a while), and races two completion
    signals: a passive ``page.on("request")`` hook that fires the moment a
    Bearer header lands on an ``amp-api`` request, and a stdin "press enter
    when done" fallback for cases where the auto-detect doesn't trip.

    The captured credentials and Playwright storage state are persisted under
    ``session_dir`` so the next run can skip the browser entirely whenever the
    cached session is still valid.
    """

    def __init__(
        self,
        session_dir: Path | str = DEFAULT_SESSION_DIR,
        *,
        headless: bool = False,
        wait_for_enter: bool = True,
    ) -> None:
        self.session_dir = Path(session_dir).expanduser()
        self.headless = headless
        self.wait_for_enter = wait_for_enter

    def authenticate(self) -> AppleMusicCredentials:
        """Run the full authentication flow.

        Restores any saved storage state, opens Chromium, lets the user sign
        in if needed, captures credentials, persists the session, and returns
        the credentials. Raises :class:`AppleMusicAuthError` if the flow
        cannot produce a working set of credentials.
        """
        raise NotImplementedError

    def load_cached(self) -> AppleMusicCredentials | None:
        """Return previously persisted credentials if still valid, else ``None``.

        Validity is checked against ``/v1/me/storefront`` before returning;
        expired credentials are treated as a cache miss.
        """
        raise NotImplementedError

    def save(self, credentials: AppleMusicCredentials) -> None:
        """Persist credentials and Playwright storage state under ``session_dir``."""
        raise NotImplementedError
