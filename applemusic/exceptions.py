"""Exception hierarchy for applemusic."""

from __future__ import annotations


class AppleMusicError(Exception):
    """Base class for all applemusic errors."""


class AppleMusicAuthError(AppleMusicError):
    """Raised when authentication fails or saved credentials are no longer valid."""


class AppleMusicHTTPError(AppleMusicError):
    """Raised when the Apple Music API returns a non-2xx response."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        response_body: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body
