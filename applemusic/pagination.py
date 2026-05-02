"""Helpers for iterating Apple Music's ``next``-cursor paginated responses.

Apple Music responses include a top-level ``next`` field with a relative URL
when more pages of results are available; these helpers walk that chain so
callers don't have to.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

Fetch = Callable[[str, "dict[str, Any] | None"], dict[str, Any]]


def paginate(
    fetch: Fetch,
    initial_url: str,
    initial_params: dict[str, Any] | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield every item across all pages of a paginated endpoint.

    ``fetch`` receives a path (or full ``next`` URL) plus an optional params
    dict and returns the parsed JSON envelope. The helper yields each entry
    from the ``data`` array, then follows ``next`` until exhausted; once a
    ``next`` URL is followed it carries its own query string, so subsequent
    calls receive ``params=None``.
    """
    next_url: str | None = initial_url
    next_params = initial_params
    while next_url:
        envelope = fetch(next_url, next_params)
        yield from envelope.get("data", [])
        next_url = envelope.get("next")
        next_params = None
