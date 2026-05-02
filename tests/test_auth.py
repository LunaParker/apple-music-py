"""Tests for AppleMusicAuth — load_cached, save, validation.

The browser flow itself is exercised by tests/integration/test_live_endpoints.py
once the user has completed an interactive sign-in.
"""

from __future__ import annotations

import json
import os

import httpx
import pytest

from applemusic import AppleMusicAuth, AppleMusicCredentials


def make_creds() -> AppleMusicCredentials:
    return AppleMusicCredentials(
        developer_token="fake.jwt.token",
        media_user_token="fake-mut",
        cookie_header="myacinfo=fake; media-user-token=fake-mut",
    )


def _ok_response(*args, **kwargs) -> httpx.Response:
    url = args[0] if args else kwargs.get("url", "https://example.com")
    return httpx.Response(200, request=httpx.Request("GET", url))


def _unauthorized_response(*args, **kwargs) -> httpx.Response:
    url = args[0] if args else kwargs.get("url", "https://example.com")
    return httpx.Response(401, request=httpx.Request("GET", url))


def test_load_cached_returns_none_if_missing(tmp_path) -> None:
    auth = AppleMusicAuth(session_dir=tmp_path)
    assert auth.load_cached() is None


def test_load_cached_returns_none_if_corrupt_json(tmp_path) -> None:
    auth = AppleMusicAuth(session_dir=tmp_path)
    (tmp_path / "credentials.json").write_text("{not valid json")
    assert auth.load_cached() is None


def test_load_cached_returns_none_if_required_field_missing(tmp_path) -> None:
    auth = AppleMusicAuth(session_dir=tmp_path)
    (tmp_path / "credentials.json").write_text(
        json.dumps({"developer_token": "only-this"})
    )
    assert auth.load_cached() is None


def test_save_then_load_round_trip(tmp_path, monkeypatch) -> None:
    auth = AppleMusicAuth(session_dir=tmp_path)
    creds = make_creds()
    auth.save(creds)

    creds_path = tmp_path / "credentials.json"
    assert creds_path.exists()
    data = json.loads(creds_path.read_text())
    assert data["developer_token"] == creds.developer_token
    assert data["media_user_token"] == creds.media_user_token
    assert data["cookie_header"] == creds.cookie_header

    monkeypatch.setattr("applemusic.auth.httpx.get", _ok_response)
    loaded = auth.load_cached()
    assert loaded == creds


def test_load_cached_returns_none_when_validation_fails(tmp_path, monkeypatch) -> None:
    auth = AppleMusicAuth(session_dir=tmp_path)
    auth.save(make_creds())

    monkeypatch.setattr("applemusic.auth.httpx.get", _unauthorized_response)
    assert auth.load_cached() is None


def test_authenticate_returns_cached_without_browser(tmp_path, monkeypatch) -> None:
    """authenticate() with valid cached creds must NOT spawn a browser."""
    auth = AppleMusicAuth(session_dir=tmp_path)
    auth.save(make_creds())

    monkeypatch.setattr("applemusic.auth.httpx.get", _ok_response)
    monkeypatch.setattr(
        AppleMusicAuth,
        "_authenticate_via_browser",
        lambda self: pytest.fail("browser path should not run when cache is valid"),
    )

    result = auth.authenticate()
    assert result == make_creds()


def test_authenticate_force_skips_cache(tmp_path, monkeypatch) -> None:
    auth = AppleMusicAuth(session_dir=tmp_path)
    auth.save(make_creds())
    monkeypatch.setattr("applemusic.auth.httpx.get", _ok_response)

    fresh = AppleMusicCredentials(
        developer_token="fresh.jwt",
        media_user_token="fresh-mut",
        cookie_header="myacinfo=fresh",
    )
    monkeypatch.setattr(
        AppleMusicAuth, "_authenticate_via_browser", lambda self: fresh
    )

    result = auth.authenticate(force=True)
    assert result == fresh


def test_validate_sends_expected_request(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_get(url, *, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["timeout"] = timeout
        return httpx.Response(200, request=httpx.Request("GET", url))

    monkeypatch.setattr("applemusic.auth.httpx.get", fake_get)

    auth = AppleMusicAuth()
    assert auth._validate(make_creds()) is True

    assert captured["url"] == "https://amp-api.music.apple.com/v1/me/storefront"
    headers = captured["headers"]
    assert headers["Authorization"] == "Bearer fake.jwt.token"
    assert headers["media-user-token"] == "fake-mut"
    assert "myacinfo=fake" in headers["Cookie"]
    assert headers["Origin"] == "https://music.apple.com"


def test_validate_returns_false_on_network_error(monkeypatch) -> None:
    def fake_get(*a, **k):
        raise httpx.ConnectError("network down")

    monkeypatch.setattr("applemusic.auth.httpx.get", fake_get)

    auth = AppleMusicAuth()
    assert auth._validate(make_creds()) is False


def test_validate_returns_false_on_401(monkeypatch) -> None:
    monkeypatch.setattr("applemusic.auth.httpx.get", _unauthorized_response)
    auth = AppleMusicAuth()
    assert auth._validate(make_creds()) is False


@pytest.mark.skipif(os.name != "posix", reason="chmod is POSIX-only")
def test_save_chmods_credentials_file(tmp_path) -> None:
    auth = AppleMusicAuth(session_dir=tmp_path)
    auth.save(make_creds())

    creds_path = tmp_path / "credentials.json"
    mode = creds_path.stat().st_mode & 0o777
    assert mode == 0o600


def test_save_creates_session_dir(tmp_path) -> None:
    nested = tmp_path / "deep" / "nest"
    auth = AppleMusicAuth(session_dir=nested)
    assert not nested.exists()

    auth.save(make_creds())

    assert nested.exists()
    assert (nested / "credentials.json").exists()
