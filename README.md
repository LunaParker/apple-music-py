# apple-music-py

> [!NOTE]
> Alpha. The full API surface (auth, library reads, library mutations, catalog reads, search, pagination) is implemented and unit-tested with mocked HTTP. Live integration tests are provided as well, but they require the user to authenticate at least once before they can run.

## Table of contents

- [Overview](#overview)
- [Why this exists](#why-this-exists)
- [What's available](#whats-available)
- [Installation and setup](#installation-and-setup)
- [Examples](#examples)
  - [Authenticating and listing the user's playlists](#authenticating-and-listing-the-users-playlists)
  - [Fetching every song in a specific playlist](#fetching-every-song-in-a-specific-playlist)
  - [Searching the catalog and looking a song up by ID](#searching-the-catalog-and-looking-a-song-up-by-id)
  - [Looking up Apple Music tracks by ISRC](#looking-up-apple-music-tracks-by-isrc)
  - [Creating a playlist and adding tracks](#creating-a-playlist-and-adding-tracks)
  - [Saving songs to the library](#saving-songs-to-the-library)
- [Configuration](#configuration)
- [Testing](#testing)
- [Licence](#licence)

## Overview

`apple-music-py` is an unofficial Python client for Apple Music's web API. It exposes a [Spotipy](https://github.com/spotipy-dev/spotipy)-shaped surface (`current_user_playlists()`, `playlist_create(...)`, `search(...)`, `catalog_song(id)`, and so on) for reading and modifying the signed-in user's own library and searching the public Apple Music catalog. Authentication runs through Playwright: on first run, a Chromium window opens and the user signs in to Apple normally (2FA included); the library then captures the developer JWT, `media-user-token`, and session cookies that music.apple.com itself uses, and subsequent runs re-use the cached session unless Apple has expired it. Pagination, retries with `Retry-After` honour, and exponential backoff are handled internally, so callers get full lists back from library reads without having to walk Apple's `next`-cursor chain themselves.

## Why this exists

Apple's official MusicKit JS pipeline requires an **Apple Developer Program** membership at **USD $99/year** to obtain the developer-signed JWT that authorises catalog access, plus a separate **Music User Token** captured through a bespoke MusicKit JS sign-in flow on a website the developer has to host themselves. That is the *only* officially-blessed way to read or modify a user's own Apple Music library from outside the iOS / macOS apps, and for end-user scripts that just want to back up a library, mirror playlists from another service, or write a quick personal automation, the friction (and the recurring fee) is hard to justify.

[Spotipy](https://github.com/spotipy-dev/spotipy), the inspiration for this project, doesn't have to deal with any of that: Spotify's developer dashboard is free, anyone with a Spotify account can register a personal app in five minutes, and the resulting OAuth flow is fully documented and supported by Spotify itself. Apple has taken a stricter view, so `apple-music-py` instead targets `amp-api.music.apple.com` directly (the exact endpoints that the music.apple.com web client uses), with credentials scraped from a real signed-in browser session via Playwright. The trade-off is that undocumented endpoints can change without notice; in practice, the shape of `amp-api` has been stable for years, but there are no guarantees.

## What's available

**User library: reads**

- `current_user_storefront()`: the user's storefront record (e.g. `us`, `ca`, `gb`).
- `current_user_saved_tracks()` / `current_user_saved_albums()` / `current_user_saved_artists()`: every song / album / artist in the user's library.
- `current_user_playlists()`: every playlist in the user's library.
- `playlist_tracks(playlist_id)`: every track in a given library playlist.
- `library_song(id)` / `library_album(id)` / `library_artist(id)` / `library_playlist(id)`: direct fetches by library ID; useful for verifying a just-created playlist exists, since `current_user_playlists()` is eventually consistent on Apple's side.

**User library: mutations**

- `playlist_create(name, description=, track_ids=, track_kind=)`
- `playlist_update(playlist_id, name=, description=)`
- `playlist_delete(playlist_id)`
- `playlist_add_tracks(playlist_id, track_ids, track_kind=)`
- `playlist_remove_track(playlist_id, track_id)`
- `library_add(songs=, albums=, artists=, music_videos=)`
- `library_remove_song(song_id)` / `library_remove_album(album_id)`

**Catalog: reads and search**

- `search(query, types=, limit=)`: `types` accepts `songs`, `albums`, `artists`, `music-videos`, `playlists`, `stations`.
- `catalog_song(id)` / `catalog_album(id)` / `catalog_artist(id)` / `catalog_playlist(id)`: direct fetches by Apple Music catalog ID.
- `catalog_songs_by_isrc(isrcs)`: batch lookup by **ISRC**, the 12-character recording identifier that almost every other music service exposes; far more reliable than fuzzy text search when migrating libraries between platforms.
- `catalog_albums_by_upc(upcs)`: batch lookup by **UPC** (album-level barcode); the album-level analogue of the ISRC lookup.

Pagination is handled internally: every library-read method walks Apple's `next`-cursor chain transparently and returns the full list. Retries with exponential backoff and `Retry-After` honour are built into the HTTP layer, so callers don't need to wrap their own retry loop around Apple's occasional 429s.

## Installation and setup

Requires Python 3.10 or newer.

```sh
pip install -e ".[dev]"
playwright install chromium
```

The first call to `auth.authenticate()` (or the `applemusic auth` CLI described below) opens a Chromium window and waits for the user to finish signing in, including any 2FA challenges Apple decides to throw up. On every subsequent run, the cached credentials at `~/.cache/applemusic/credentials.json` are restored and the browser only re-opens if the session has actually expired.

> [!IMPORTANT]
> **Cookies and tokens never leave the user's local machine.** The captured developer JWT, `media-user-token`, and session cookie jar are written to `~/.cache/applemusic/credentials.json` (mode `0600` on POSIX) and read straight back from disk on subsequent runs. The library has no telemetry, no upstream callbacks, and no servers of its own: every HTTP request goes directly from the user's process to `amp-api.music.apple.com`, the same endpoint that music.apple.com itself uses.

To authenticate from the command line without writing any Python (useful before running scripts, or as a once-per-six-months refresh when Apple rotates the developer JWT):

```sh
python -m applemusic auth
# or, after pip install:
applemusic auth
# pass --force to skip the cache and re-prompt:
applemusic auth --force
```

## Examples

Each example below assumes that `auth.authenticate()` has been run at least once already (either via the CLI above or via an earlier Python invocation). On subsequent runs, `auth.authenticate()` returns instantly from the cache without re-opening the browser. A self-contained "sign in then dump the library to JSON" script also lives at [`examples/login_and_dump.py`](examples/login_and_dump.py).

### Authenticating and listing the user's playlists

```python
from applemusic import AppleMusic, AppleMusicAuth

auth = AppleMusicAuth()
credentials = auth.authenticate()  # opens Chromium on first run; cached afterwards

with AppleMusic(credentials) as client:
    playlists = client.current_user_playlists()
    for playlist in playlists:
        attrs = playlist["attributes"]
        print(f"{playlist['id']}\t{attrs['name']}")
```

Expected output (one row per library playlist; Apple's own ordering, newest first):

```
p.LV0p2VAUxvBR	Sunday morning rotation
p.AWXQ5BIZX9MV	Late-night focus
p.EkjJDdltq2pQ	Gym 2026
…
```

### Fetching every song in a specific playlist

Combine `current_user_playlists()` with `playlist_tracks(playlist_id)` to walk every track in a given playlist. Pagination is handled internally, so the returned list is the full thing, with no `next`-cursor walking required, even for very large playlists.

```python
playlist_id = "p.LV0p2VAUxvBR"

with AppleMusic(credentials) as client:
    tracks = client.playlist_tracks(playlist_id)
    for track in tracks:
        attrs = track["attributes"]
        print(f"{attrs['artistName']} — {attrs['name']}")
```

### Searching the catalog and looking a song up by ID

`search(...)` returns the raw `results` envelope keyed by type; each section carries a `data` array of catalog records. Once a song's catalog ID is in hand, `catalog_song(id)` returns the full record without a second search round-trip.

```python
with AppleMusic(credentials) as client:
    results = client.search("bohemian rhapsody", types=["songs"], limit=5)
    for song in results.get("songs", {}).get("data", []):
        attrs = song["attributes"]
        print(f"{song['id']}\t{attrs['artistName']} — {attrs['name']}")

    # Direct catalog fetch by ID — no search round-trip needed when the ID is known.
    song = client.catalog_song("1440806041")
    print(song["attributes"]["name"], "by", song["attributes"]["artistName"])
```

### Looking up Apple Music tracks by ISRC

When migrating a library from another service (Spotify, Deezer, Tidal, or anything else that exposes ISRCs), looking matches up by the 12-character **ISRC** is far more reliable than fuzzy text search: the ISRC uniquely identifies a specific recording, so there's no ambiguity between studio versions, live versions, remasters, and so on.

```python
with AppleMusic(credentials) as client:
    matches = client.catalog_songs_by_isrc(["GBUM71029604", "USRC11400001"])
    for song in matches:
        attrs = song["attributes"]
        print(attrs["isrc"], "→", song["id"], attrs["name"])
```

`catalog_albums_by_upc(...)` works the same way for album-level barcodes (UPC / EAN).

### Creating a playlist and adding tracks

`playlist_create(...)` returns the new playlist envelope, including the assigned ID. Any tracks passed via `track_ids=` are added at creation time; `playlist_add_tracks(...)` appends more later.

```python
with AppleMusic(credentials) as client:
    playlist = client.playlist_create(
        name="Imported from Spotify",
        description="Migration test, 2026-05-04",
        track_ids=["1440806041", "1440806042"],
    )
    new_id = playlist["id"]
    print("Created playlist", new_id)

    # Append more tracks later:
    client.playlist_add_tracks(new_id, ["1440806043", "1440806044"])
```

### Saving songs to the library

`library_add(...)` accepts catalog IDs (not library IDs), which Apple converts on ingest. Pass any combination of `songs=`, `albums=`, `artists=`, and `music_videos=`.

```python
with AppleMusic(credentials) as client:
    client.library_add(songs=["1440806041", "1440806042"])
```

## Configuration

Both `AppleMusic` and `AppleMusicAuth` are usable with no arguments beyond the credentials, but every behaviour the library applies on the user's behalf (the storefront it queries, the retry budget, where credentials live on disk) is exposed as a keyword argument on the relevant constructor.

### `AppleMusic(credentials, ...)`

- `storefront=None`: Apple Music storefront identifier (e.g. `"us"`, `"ca"`, `"gb"`). When left as `None`, the client looks the value up via `/v1/me/storefront` on the first catalog call and caches the result for the lifetime of the instance; pass it explicitly to skip that round-trip.
- `language="en-US"`: sent on every request as the `Accept-Language` header and as the `l=` query parameter; controls localised attributes such as artist names and editorial notes.
- `timeout=30.0`: per-request timeout in seconds, forwarded to the underlying `httpx.Client`.
- `max_retries=3`: number of retries on top of the initial attempt for transient failures (HTTP 429 / 500 / 502 / 503 / 504, plus network-layer errors). Set to `0` to disable retries entirely.
- `retry_backoff=1.0`: base for the exponential backoff used between retries. Each retry sleeps for a random value between 0 and `retry_backoff * 2 ** attempt` seconds (full-jitter).
- `retry_backoff_max=30.0`: upper bound on any single retry sleep, applied both to the exponential schedule above and to the `Retry-After` header honoured on 429 responses.

### `AppleMusicAuth(...)`

- `session_dir=~/.cache/applemusic`: directory used for the cached credentials JSON, the persistent Chromium profile, and the Playwright storage state. Override it to share a session between accounts or to keep credentials under a project-local directory.
- `headless=False`: passing `True` launches Chromium without a window. **Sign-in won't actually complete in headless mode** (Apple's flow needs visible interaction, including 2FA), so this is only useful for re-validating an already-signed-in profile in CI-like environments.
- `wait_for_enter=True`: when `True`, the auth flow accepts a stdin "press Enter when done" signal in addition to auto-detecting the captured `Bearer` header. Set to `False` in fully non-interactive contexts where stdin isn't available.
- `auth_timeout=600.0`: seconds to wait for sign-in completion before raising `AppleMusicAuthError`. The default of ten minutes is generous on purpose; Apple's 2FA prompts can stall for a while.

## Testing

```sh
pytest tests/                # unit tests (mocked HTTP); always runnable
pytest tests/integration/    # live tests against amp-api; needs prior auth
```

Integration tests use `AppleMusicAuth.load_cached()` to find credentials and skip with a helpful message if no cached session exists. The mutation tests create temporary playlists prefixed `applemusic-py integration test` and clean them up via `try` / `finally`, so the suite is safe to run repeatedly against the user's own library. If something crashes mid-test, the orphaned playlist can be deleted manually.

## Licence

[MIT](LICENSE.md).
