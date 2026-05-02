"""Helpers for iterating Apple Music's ``next``-cursor paginated responses.

Apple Music responses include a top-level ``next`` field with a relative URL
when more pages of results are available; these helpers walk that chain so
the caller doesn't have to.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any


def paginate(
    fetch: Callable[[str], dict[str, Any]],
    initial_url: str,
) -> Iterator[dict[str, Any]]:
    """Yield every item across all pages of a paginated endpoint.

    ``fetch`` should perform a GET against the supplied URL and return the
    parsed JSON envelope (including any ``next`` field). The helper yields
    each entry from the ``data`` array, then follows ``next`` until exhausted.
    """
    raise NotImplementedError
