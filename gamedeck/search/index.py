"""SearchIndex — ranked, abbreviation-aware, zero-dependency game search engine."""

from __future__ import annotations

from dataclasses import dataclass, field

from gamedeck.models import Game
from gamedeck.search.tokenizer import normalize, tokenize

__all__ = ["SearchIndex", "SearchResult"]


@dataclass(slots=True)
class SearchResult:
    """A single ranked search result.

    Attributes:
        game: The matched :class:`~gamedeck.models.Game` instance.
        score: Match confidence from ``0.0`` (no match) to ``1.0`` (exact
            title).  Higher scores are returned first.
        matched_tokens: The token strings that triggered the match, useful
            for highlighting or debugging.
    """

    game: Game
    score: float
    matched_tokens: list[str]


# ---------------------------------------------------------------------------
# Internal entry type
# ---------------------------------------------------------------------------

# Each indexed game is stored as (game, token_set, normalized_title).
# Using a plain tuple keeps memory flat and avoids an extra dataclass.
_Entry = tuple[Game, frozenset[str], str]

# ---------------------------------------------------------------------------
# Score tiers (never change the numeric values; tests assert on them)
# ---------------------------------------------------------------------------

_SCORE_EXACT_TITLE: float = 1.00   # query == full normalised title
_SCORE_EXACT_TOKEN: float = 0.95   # query == one indexed token (e.g. acronym "bmw")
_SCORE_PREFIX_TITLE: float = 0.85  # normalised_title.startswith(query)
_SCORE_PREFIX_TOKEN: float = 0.75  # any token.startswith(query)
_SCORE_SUB_TITLE: float = 0.60     # query in normalised_title (substring)
_SCORE_SUB_TOKEN: float = 0.50     # query in any token
_WORD_BONUS: float = 0.10          # all query words matched individually
_WORD_BONUS_CAP: float = 0.99      # multi-word bonus never reaches 1.0


@dataclass(slots=True)
class SearchIndex:
    """In-memory search index for fast, ranked game lookup.

    Supports:

    - **Abbreviation matching** — ``"BMW"`` → *Black Myth: Wukong*
    - **Partial matching** — ``"elden"`` → *Elden Ring*
    - **Punctuation removal** — ``"counter strike"`` → *Counter-Strike 2*
    - **Case-insensitive matching** — ``"ELDEN RING"`` == ``"elden ring"``
    - **Ranked results** — exact title > acronym > prefix > substring

    Build the index once, query many times::

        index = SearchIndex.build(games)
        results = index.search("BMW")
        for r in results:
            print(r.score, r.game.name)

    Attributes:
        _entries: Internal list of ``(game, token_set, normalized_title)``
            triples.  Do not modify directly; use :meth:`add`.
    """

    _entries: list[_Entry] = field(
        default_factory=list, init=False, repr=False
    )

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def build(cls, games: list[Game], tags_map: dict[str, list[str]] | None = None) -> SearchIndex:
        """Build a :class:`SearchIndex` from a list of games.

        Args:
            games: List of :class:`~gamedeck.models.Game` instances to index.
            tags_map: Optional dictionary mapping game.id to list of assigned tags.

        Returns:
            A populated :class:`SearchIndex` ready for querying.
        """
        idx = cls()
        for game in games:
            tags = tags_map.get(game.id) if tags_map else None
            idx.add(game, tags=tags)
        return idx

    def add(self, game: Game, tags: list[str] | None = None) -> None:
        """Add a single game to the index.

        Calling :meth:`build` is preferred when constructing from a batch.

        Args:
            game: :class:`~gamedeck.models.Game` instance to index.
            tags: Optional list of assigned tag names.
        """
        tokens = tokenize(
            name=game.name,
            appid=game.appid,
            source=game.source,
            executable=game.executable,
            tags=tags,
        )
        normalized_title = normalize(game.name)
        # Collapse multi-space after normalize (split+join cleans up)
        normalized_title = " ".join(normalized_title.split())
        self._entries.append((game, tokens, normalized_title))

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------

    def search(self, query: str, limit: int = 0) -> list[SearchResult]:
        """Search the index and return ranked results.

        Queries are case-insensitive and punctuation-insensitive.
        Results are sorted by score (descending) then game name
        (ascending, for stable tie-breaking).

        Args:
            query: Search string — e.g. ``"BMW"``, ``"elden ring"``,
                ``"counter-strike"``.
            limit: Maximum number of results to return.  ``0`` means no cap.

        Returns:
            :class:`list` of :class:`SearchResult` sorted best-first.
        """
        q = " ".join(normalize(query).split()).strip()
        if not q:
            return []

        results: list[SearchResult] = []

        for game, tokens, normalized_title in self._entries:
            score, matched = self._score(q, tokens, normalized_title)
            if score > 0.0:
                results.append(
                    SearchResult(game=game, score=score, matched_tokens=matched)
                )

        results.sort(key=lambda r: (-r.score, r.game.name.lower()))

        if limit > 0:
            results = results[:limit]

        return results

    def __len__(self) -> int:
        """Return the number of indexed games."""
        return len(self._entries)

    # ------------------------------------------------------------------
    # Scoring (private)
    # ------------------------------------------------------------------

    def _score(
        self,
        query: str,
        tokens: frozenset[str],
        normalized_title: str,
    ) -> tuple[float, list[str]]:
        """Compute the best match score for one indexed game.

        Handles both single-word and multi-word queries.  Multi-word
        queries earn a bonus when *every* query word independently matches,
        producing a combined score above any single-word partial match.

        Args:
            query: Already-normalised query string.
            tokens: Full token set for the candidate game.
            normalized_title: Normalised display title of the candidate game.

        Returns:
            ``(score, matched_tokens)`` — score ``0.0`` means no match.
        """
        query_words = query.split()

        # --- Treat query as a single phrase ---
        full_score, full_matched = self._score_phrase(query, tokens, normalized_title)

        # --- Per-word scoring for multi-word queries ---
        if len(query_words) > 1:
            word_results = [
                self._score_word(w, tokens, normalized_title)
                for w in query_words
            ]

            if all(s > 0.0 for s, _ in word_results):
                min_word_score = min(s for s, _ in word_results)
                # Bonus for all words matching, but never reach 1.0
                combined = min(_WORD_BONUS_CAP, min_word_score + _WORD_BONUS)
                if combined > full_score:
                    all_matched = [m for _, ms in word_results for m in ms]
                    return combined, all_matched

        return full_score, full_matched

    def _score_phrase(
        self,
        phrase: str,
        tokens: frozenset[str],
        normalized_title: str,
    ) -> tuple[float, list[str]]:
        """Score a single phrase against one game entry.

        Scoring tiers, evaluated top-down (first match wins):

        1. ``1.00`` — phrase exactly equals the full normalised title
        2. ``0.95`` — phrase exactly equals any indexed token (e.g. acronym)
        3. ``0.85`` — normalised title *starts with* phrase
        4. ``0.75`` — any token *starts with* phrase (≥ 2 chars)
        5. ``0.60`` — phrase is a *substring* of the full normalised title
        6. ``0.50`` — phrase is a *substring* of any token (≥ 2 chars)
        """
        if phrase == normalized_title:
            return _SCORE_EXACT_TITLE, ["exact_title"]

        if phrase in tokens:
            return _SCORE_EXACT_TOKEN, [f"exact_token:{phrase}"]

        if normalized_title.startswith(phrase):
            return _SCORE_PREFIX_TITLE, ["prefix_title"]

        if len(phrase) >= 2:
            for token in tokens:
                if token.startswith(phrase) and token != phrase:
                    return _SCORE_PREFIX_TOKEN, [f"prefix_token:{token}"]

        if phrase in normalized_title:
            return _SCORE_SUB_TITLE, ["sub_title"]

        if len(phrase) >= 2:
            for token in tokens:
                if phrase in token:
                    return _SCORE_SUB_TOKEN, [f"sub_token:{token}"]

        return 0.0, []

    def _score_word(
        self,
        word: str,
        tokens: frozenset[str],
        normalized_title: str,
    ) -> tuple[float, list[str]]:
        """Score a single word (component of a multi-word query)."""
        if word in tokens:
            return _SCORE_EXACT_TOKEN, [f"exact_token:{word}"]

        if normalized_title.startswith(word):
            return _SCORE_PREFIX_TITLE, ["prefix_title"]

        if len(word) >= 2:
            for token in tokens:
                if token.startswith(word):
                    return _SCORE_PREFIX_TOKEN, [f"prefix_token:{token}"]

        if word in normalized_title:
            return _SCORE_SUB_TITLE, ["sub_title"]

        if len(word) >= 2:
            for token in tokens:
                if word in token:
                    return _SCORE_SUB_TOKEN, [f"sub_token:{token}"]

        return 0.0, []
