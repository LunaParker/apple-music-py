"""Import smoke tests — the package must import cleanly without credentials."""

from __future__ import annotations

import applemusic


def test_package_exports() -> None:
    assert hasattr(applemusic, "AppleMusic")
    assert hasattr(applemusic, "AppleMusicAuth")
    assert hasattr(applemusic, "AppleMusicCredentials")
    assert hasattr(applemusic, "AppleMusicError")
    assert hasattr(applemusic, "AppleMusicAuthError")
    assert hasattr(applemusic, "AppleMusicHTTPError")
    assert applemusic.__version__ == "0.0.1"
