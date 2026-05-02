# apple-music-py

Unofficial Python client for the Apple Music web API. Spotipy-shaped surface, with Playwright-driven authentication so the user signs in once in a real browser and the library handles capturing the developer JWT, `media-user-token`, and session cookies automatically — no Apple Developer Program licence required.

> [!NOTE]
> Alpha. The full API surface — auth, library reads, library mutations, catalog reads, search, pagination — is implemented and unit-tested with mocked HTTP. Live integration tests are provided as well, but they require the user to authenticate at least once before they can run.

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
    queen = client.search("Queen", types=["artists"], limit=5)
```

The first call spawns a Chromium window and waits for the user to finish signing in (including any 2FA prompts Apple decides to throw up); on subsequent runs, the cached credentials at `~/.cache/applemusic/credentials.json` are restored and the browser only opens if the session has actually expired.

To authenticate from the command line without writing any Python — useful before running scripts, or as a once-per-six-months refresh:

```sh
python -m applemusic auth
# or, after pip install:
applemusic auth
# pass --force to skip the cache and re-prompt:
applemusic auth --force
```

## What's available

User library (read):

- `current_user_storefront()`
- `current_user_saved_tracks()`, `current_user_saved_albums()`, `current_user_saved_artists()`
- `current_user_playlists()`, `playlist_tracks(playlist_id)`
- `library_song(id)`, `library_album(id)`, `library_artist(id)`, `library_playlist(id)` — single-item fetches; useful for verifying a just-created playlist exists, since `current_user_playlists()` is eventually consistent on Apple's side

User library (mutations):

- `playlist_create(name, description=, track_ids=, track_kind=)`
- `playlist_update(playlist_id, name=, description=)`
- `playlist_delete(playlist_id)`
- `playlist_add_tracks(playlist_id, track_ids, track_kind=)`
- `playlist_remove_track(playlist_id, track_id)`
- `library_add(songs=, albums=, artists=, music_videos=)`
- `library_remove_song(song_id)`, `library_remove_album(album_id)`

Catalog:

- `search(query, types=, limit=)` — types: `songs`, `albums`, `artists`, `music-videos`, `playlists`, `stations`
- `catalog_song(id)`, `catalog_album(id)`, `catalog_artist(id)`, `catalog_playlist(id)`
- `catalog_songs_by_isrc(isrcs)`, `catalog_albums_by_upc(upcs)` — batch lookup by industry-standard identifiers; useful when migrating libraries from another service that exposes ISRCs/UPCs (e.g. Spotify), since they're far more reliable than fuzzy text search

Pagination is handled internally — the library reads return full lists, walking Apple's `next`-cursor chain transparently.

## Testing

```sh
pytest tests/                # unit tests (mocked HTTP); always runnable
pytest tests/integration/    # live tests against amp-api; needs prior auth
```

Integration tests use `AppleMusicAuth.load_cached()` to find credentials and skip with a helpful message if no cached session exists. The mutation tests create temporary playlists prefixed `applemusic-py integration test` and clean them up via `try`/`finally`, so the suite is safe to run repeatedly against the user's own library — assuming nothing crashes mid-test, in which case the orphaned playlist can be deleted manually.

## Why an unofficial API?

Apple's official MusicKit JS pipeline requires an Apple Developer Program membership (USD $99/year) plus a developer-signed JWT for catalog access and a Music User Token obtained via a bespoke MusicKit JS sign-in flow. For end-user scripts that just want to read or modify the user's own library, that is a lot of friction. `apple-music-py` instead targets `amp-api.music.apple.com` — the same endpoints the music.apple.com web client uses — with credentials scraped from a real signed-in browser session.

The trade-off is that undocumented endpoints can change without notice; in practice, the shape of `amp-api` has been stable for years, but there are no guarantees.

## Licence

[MIT](LICENSE).
