"""Command-line entry point: ``python -m applemusic`` (or ``applemusic`` after install)."""

from __future__ import annotations

import sys

from applemusic.auth import AppleMusicAuth
from applemusic.exceptions import AppleMusicAuthError

_USAGE = """\
Usage: applemusic auth

Subcommands:
  auth      Open Chromium for Apple Music sign-in and cache the resulting
            credentials at ~/.cache/applemusic/credentials.json. Subsequent
            invocations skip the browser when the cached session is still
            valid; pass `--force` after `auth` to ignore the cache.
"""


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    if not args or args[0] in ("-h", "--help"):
        print(_USAGE)
        return 0

    if args[0] != "auth":
        print(f"Unknown command: {args[0]!r}\n", file=sys.stderr)
        print(_USAGE, file=sys.stderr)
        return 2

    force = "--force" in args[1:]

    try:
        auth = AppleMusicAuth()
        auth.authenticate(force=force)
    except AppleMusicAuthError as e:
        print(f"\n[applemusic] Authentication failed: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n[applemusic] Authentication cancelled.", file=sys.stderr)
        return 130
    else:
        print(
            f"\n[applemusic] Authentication complete.\n"
            f"             Credentials cached at {auth.session_dir}/credentials.json"
        )
        return 0


if __name__ == "__main__":
    sys.exit(main())
