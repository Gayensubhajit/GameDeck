"""Search engine package for GameDeck."""

from __future__ import annotations

from gamedeck.models import Game
from gamedeck.search.index import SearchIndex, SearchResult
from gamedeck.search.tokenizer import normalize, tokenize

__all__ = [
    "SearchIndex",
    "SearchResult",
    "index_games",
    "search",
    "tokenize",
    "normalize",
]


def index_games(games: list[Game]) -> SearchIndex:
    """Convenience function to build a SearchIndex from a list of games.

    Args:
        games: List of Game model instances.

    Returns:
        Populated SearchIndex instance.
    """
    return SearchIndex.build(games)


def search(games: list[Game], query: str, limit: int = 0) -> list[SearchResult]:
    """Convenience function to build an index and search games in one step.

    Args:
        games: List of Game model instances to search over.
        query: Search query string.
        limit: Maximum number of results to return (0 for unlimited).

    Returns:
        List of ranked SearchResult instances.
    """
    index = SearchIndex.build(games)
    return index.search(query, limit=limit)
