"""Authenticate once and dump the user's library to JSON.

Run with ``python examples/login_and_dump.py``. A Chromium window opens; sign
in to your Apple ID, then return to the terminal — credentials are captured
and the session is reused on subsequent runs.
"""

from __future__ import annotations

import json
from pathlib import Path

from applemusic import AppleMusic, AppleMusicAuth


def main() -> None:
    auth = AppleMusicAuth()
    credentials = auth.authenticate()

    with AppleMusic(credentials) as client:
        playlists = client.current_user_playlists()
        tracks = client.current_user_saved_tracks()

    Path("playlists.json").write_text(json.dumps(playlists, indent=2))
    Path("songs.json").write_text(json.dumps(tracks, indent=2))
    print(f"Wrote {len(playlists)} playlists and {len(tracks)} songs.")


if __name__ == "__main__":
    main()
