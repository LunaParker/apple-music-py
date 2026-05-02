# apple-music-py

Unofficial Python client for the Apple Music web API. Spotipy-shaped surface, with Playwright-driven authentication so the user signs in once in a real browser and the library handles capturing the developer JWT, `media-user-token`, and session cookies automatically — no Apple Developer Program licence required.

> [!WARNING]
> Pre-alpha. The package layout, public API surface, and `pyproject.toml` are in place; the auth and client implementations are scaffolded but not yet written.

## Installation

```sh
pip install -e ".[dev]"
playwright install chromium
```

Requires Python 3.10 or newer.

## Quick start

```python
from applemusic import AppleMusic, AppleMusicAuth

auth = AppleMusicAuth()
credentials = auth.authenticate()  # opens Chromium; sign in interactively

with AppleMusic(credentials) as client:
    playlists = client.current_user_playlists()
    songs = client.current_user_saved_tracks()
```

The first call spawns a Chromium window and waits for the user to finish signing in (including any 2FA prompts Apple decides to throw up); on subsequent runs, the cached Playwright storage state is restored and the browser only opens if the session has actually expired.

## Why an unofficial API?

Apple's official MusicKit JS pipeline requires an Apple Developer Program membership (USD $99/year) plus a developer-signed JWT for catalog access and a Music User Token obtained via a bespoke MusicKit JS sign-in flow. For end-user scripts that just want to read or modify the user's own library, that is a lot of friction. `apple-music-py` instead targets `amp-api.music.apple.com` — the same endpoints the music.apple.com web client uses — with credentials scraped from a real signed-in browser session.

The trade-off is that undocumented endpoints can change without notice; in practice, the shape of `amp-api` has been stable for years, but no guarantees.

## Licence

[MIT](LICENSE).
