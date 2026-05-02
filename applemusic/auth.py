"""Browser-driven authentication for Apple Music.

Spawns a headed Chromium via Playwright, lets the user complete sign-in
(including 2FA) on their own timeline, then captures the developer JWT, the
per-user ``media-user-token``, and the session cookie jar so subsequent
requests to ``amp-api.music.apple.com`` succeed without further interaction.
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from applemusic.exceptions import AppleMusicAuthError

if TYPE_CHECKING:
    from playwright.sync_api import BrowserContext

DEFAULT_SESSION_DIR = Path.home() / ".cache" / "applemusic"

APPLE_MUSIC_HOME = "https://music.apple.com"
AMP_API_BASE = "https://amp-api.music.apple.com"

CREDENTIALS_FILENAME = "credentials.json"
STORAGE_STATE_FILENAME = "storage-state.json"


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

    The flow opens a headed Chromium window with a persistent profile, lets
    the user complete sign-in at their own pace (Apple's 2FA can take a
    while), and races two completion signals: a passive
    ``page.on("request")`` hook that fires the moment a Bearer header lands
    on an ``amp-api`` request, and a stdin "press enter when done" fallback
    for cases where the auto-detect doesn't trip on its own. The captured
    credentials and Playwright storage state are persisted under
    ``session_dir`` so the next run can skip the browser entirely whenever
    the cached session is still valid.
    """

    def __init__(
        self,
        session_dir: Path | str = DEFAULT_SESSION_DIR,
        *,
        headless: bool = False,
        wait_for_enter: bool = True,
        auth_timeout: float = 600.0,
    ) -> None:
        self.session_dir = Path(session_dir).expanduser()
        self.headless = headless
        self.wait_for_enter = wait_for_enter
        self.auth_timeout = auth_timeout

    def authenticate(self, *, force: bool = False) -> AppleMusicCredentials:
        """Run the full authentication flow.

        Returns cached credentials when they exist and are still accepted by
        ``/v1/me/storefront``, unless ``force=True``. Otherwise opens a
        Chromium window and walks the user through sign-in.
        """
        if not force:
            cached = self.load_cached()
            if cached is not None:
                return cached
        return self._authenticate_via_browser()

    def load_cached(self) -> AppleMusicCredentials | None:
        """Return previously persisted credentials if still valid, else ``None``.

        Validity is checked against ``/v1/me/storefront`` before returning;
        expired credentials are treated as a cache miss.
        """
        creds_path = self.session_dir / CREDENTIALS_FILENAME
        if not creds_path.exists():
            return None
        try:
            data = json.loads(creds_path.read_text())
            credentials = AppleMusicCredentials(
                developer_token=data["developer_token"],
                media_user_token=data["media_user_token"],
                cookie_header=data["cookie_header"],
            )
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            return None
        if not self._validate(credentials):
            return None
        return credentials

    def save(self, credentials: AppleMusicCredentials) -> None:
        """Persist credentials JSON under ``session_dir`` (mode 0600 on POSIX)."""
        self.session_dir.mkdir(parents=True, exist_ok=True)
        creds_path = self.session_dir / CREDENTIALS_FILENAME
        creds_path.write_text(json.dumps(asdict(credentials), indent=2))
        if os.name == "posix":
            with contextlib.suppress(OSError):
                creds_path.chmod(0o600)

    # ----------------------------------------------------------- internal

    def _validate(self, credentials: AppleMusicCredentials) -> bool:
        try:
            response = httpx.get(
                f"{AMP_API_BASE}/v1/me/storefront",
                headers={
                    "Authorization": f"Bearer {credentials.developer_token}",
                    "media-user-token": credentials.media_user_token,
                    "Cookie": credentials.cookie_header,
                    "Origin": APPLE_MUSIC_HOME,
                    "Referer": f"{APPLE_MUSIC_HOME}/",
                    "Accept": "application/json",
                },
                timeout=10.0,
            )
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    def _authenticate_via_browser(self) -> AppleMusicCredentials:
        from playwright.sync_api import sync_playwright

        self.session_dir.mkdir(parents=True, exist_ok=True)
        profile_dir = self.session_dir / "browser-profile"
        captured_tokens: list[str] = []

        def on_request(request: Any) -> None:
            if "amp-api.music.apple.com" not in request.url:
                return
            auth_header = request.headers.get("authorization", "")
            if not auth_header.startswith("Bearer "):
                return
            token = auth_header[len("Bearer ") :]
            if token and token not in captured_tokens:
                captured_tokens.append(token)

        ready_event = threading.Event()

        def stdin_waiter() -> None:
            with contextlib.suppress(EOFError, KeyboardInterrupt):
                input(
                    "\n[applemusic] A Chromium window has opened. Sign in to your\n"
                    "             Apple ID, complete any 2FA challenges, and once\n"
                    "             you see your music.apple.com home page, return\n"
                    "             here and press Enter to capture credentials.\n"
                )
            ready_event.set()

        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                str(profile_dir),
                headless=self.headless,
                viewport={"width": 1280, "height": 800},
                args=["--disable-blink-features=AutomationControlled"],
            )
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.on("request", on_request)

                try:
                    page.goto(
                        APPLE_MUSIC_HOME,
                        wait_until="domcontentloaded",
                        timeout=60_000,
                    )
                except Exception as e:
                    raise AppleMusicAuthError(
                        f"Failed to load music.apple.com: {e}"
                    ) from e

                if self.wait_for_enter:
                    threading.Thread(target=stdin_waiter, daemon=True).start()

                deadline = time.time() + self.auth_timeout
                while time.time() < deadline:
                    if self._has_captured_credentials(context, captured_tokens):
                        break
                    if self.wait_for_enter and ready_event.is_set():
                        break
                    page.wait_for_timeout(500)
                else:
                    raise AppleMusicAuthError(
                        f"Timed out waiting for sign-in after "
                        f"{self.auth_timeout:.0f}s"
                    )

                # Pump the loop so any requests queued during the stdin wait
                # are dispatched to our on_request listener.
                page.wait_for_timeout(2000)

                if not captured_tokens:
                    # No amp-api request fired during the wait; nudge MusicKit
                    # by navigating to the library, which always triggers one.
                    try:
                        page.goto(
                            f"{APPLE_MUSIC_HOME}/library/songs",
                            wait_until="domcontentloaded",
                            timeout=30_000,
                        )
                        page.wait_for_timeout(3000)
                    except Exception:
                        pass

                credentials = self._capture_credentials(context, captured_tokens)

                if not self._validate(credentials):
                    raise AppleMusicAuthError(
                        "Captured credentials failed validation against "
                        "/v1/me/storefront. Sign-in may not have completed."
                    )

                self._save_storage_state(context)
                self.save(credentials)
                return credentials
            finally:
                context.close()

    def _has_captured_credentials(
        self,
        context: BrowserContext,
        captured_tokens: list[str],
    ) -> bool:
        if not captured_tokens:
            return False
        cookies = context.cookies(APPLE_MUSIC_HOME)
        return any(c["name"] == "media-user-token" for c in cookies)

    def _capture_credentials(
        self,
        context: BrowserContext,
        captured_tokens: list[str],
    ) -> AppleMusicCredentials:
        if not captured_tokens:
            raise AppleMusicAuthError(
                "No `Authorization: Bearer` header was intercepted on any "
                "amp-api.music.apple.com request — sign-in didn't complete."
            )

        cookies = list(context.cookies(APPLE_MUSIC_HOME))
        media_user_token_cookie = next(
            (c for c in cookies if c["name"] == "media-user-token"),
            None,
        )
        if media_user_token_cookie is None:
            amp_cookies = context.cookies(AMP_API_BASE)
            media_user_token_cookie = next(
                (c for c in amp_cookies if c["name"] == "media-user-token"),
                None,
            )
            if media_user_token_cookie is None:
                raise AppleMusicAuthError(
                    "media-user-token cookie missing — sign-in didn't complete."
                )
            cookies.extend(amp_cookies)

        cookie_header = "; ".join(f"{c['name']}={c['value']}" for c in cookies)

        return AppleMusicCredentials(
            developer_token=captured_tokens[-1],
            media_user_token=media_user_token_cookie["value"],
            cookie_header=cookie_header,
        )

    def _save_storage_state(self, context: BrowserContext) -> None:
        storage_state_path = self.session_dir / STORAGE_STATE_FILENAME
        context.storage_state(path=str(storage_state_path))
        if os.name == "posix":
            with contextlib.suppress(OSError):
                storage_state_path.chmod(0o600)
