"""Unofficial Python client for the Apple Music web API."""

from applemusic.auth import AppleMusicAuth, AppleMusicCredentials
from applemusic.client import AppleMusic
from applemusic.exceptions import (
    AppleMusicAuthError,
    AppleMusicError,
    AppleMusicHTTPError,
)

__version__ = "0.0.1"

__all__ = [
    "AppleMusic",
    "AppleMusicAuth",
    "AppleMusicAuthError",
    "AppleMusicCredentials",
    "AppleMusicError",
    "AppleMusicHTTPError",
]
