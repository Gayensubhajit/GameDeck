"""Provider manager for aggregating, deduplicating, and prioritizing game libraries."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from gamedeck.models import Game

__all__ = ["ProviderManager", "get_all_games", "PROVIDER_PRIORITY"]

# Provider priority hierarchy (higher value = higher precedence)
# Order: Steam > Heroic > Lutris > Native > Filesystem
PROVIDER_PRIORITY: dict[str, int] = {
    "steam": 50,
    "heroic": 40,
    "lutris": 30,
    "native": 20,
    "filesystem": 10,
}


class GameProvider(Protocol):
    """Protocol for provider instances that implement get_games."""

    def get_games(self) -> list[Game]:
        """Retrieve a list of discovered Game model instances."""
        ...


@dataclass(slots=True)
class ProviderManager:
    """Manager for orchestrating game discovery across all enabled providers.

    Loads enabled providers, merges their results, deduplicates games by unique
    identifier and normalized title according to provider priority
    (Steam > Heroic > Lutris > Native > Filesystem), and returns a sorted list.

    Attributes:
        enabled_providers: List of provider names to query (case-insensitive).
        custom_providers: Mapping of provider names to custom provider callables or instances.
    """

    enabled_providers: list[str] = field(
        default_factory=lambda: ["steam", "heroic", "lutris", "native", "filesystem"]
    )
    custom_providers: dict[str, Callable[[], list[Game]] | GameProvider] = field(
        default_factory=dict
    )

    def get_games(self) -> list[Game]:
        """Query all enabled providers and return a deduplicated, sorted list of games.

        Returns:
            A sorted list of Game instances.
        """
        all_games: list[Game] = []

        for provider_name in self.enabled_providers:
            provider_key = provider_name.lower().strip()
            games = self._load_provider_games(provider_key)
            all_games.extend(games)

        return self.merge_and_deduplicate(all_games)

    def merge_and_deduplicate(self, games: list[Game]) -> list[Game]:
        """Deduplicate games by unique identifier and name, applying provider precedence.

        When duplicate names or unique IDs exist, the game from the higher priority
        provider (Steam > Heroic > Lutris > Native > Filesystem) is retained.

        Args:
            games: Unfiltered list of Game instances from all providers.

        Returns:
            A deduplicated list of Game instances sorted alphabetically by name.
        """
        # Pass 1: Deduplicate by unique game id
        by_id: dict[str, Game] = {}
        for game in games:
            if not game.id:
                continue
            if game.id not in by_id:
                by_id[game.id] = game
            else:
                existing = by_id[game.id]
                if self._get_priority(game.source) > self._get_priority(existing.source):
                    by_id[game.id] = game

        # Pass 2: Deduplicate by normalized title
        by_title: dict[str, Game] = {}
        for game in by_id.values():
            title_key = self.normalize_title(game.name)
            if not title_key:
                # If name is blank, keep under unique ID
                title_key = f"__id_{game.id}"

            if title_key not in by_title:
                by_title[title_key] = game
            else:
                existing = by_title[title_key]
                if self._get_priority(game.source) > self._get_priority(existing.source):
                    by_title[title_key] = game

        # Sort alphabetically by display title (case-insensitive) then by id
        return sorted(
            by_title.values(),
            key=lambda g: (g.name.lower().strip(), g.id),
        )

    def normalize_title(self, name: str) -> str:
        """Normalize game title for duplicate matching across different providers.

        Args:
            name: Raw display name of the game.

        Returns:
            Cleaned alphanumeric lowercase title string.
        """
        lowered = name.lower().strip()
        # Strip special punctuation while keeping letters and digits
        cleaned = re.sub(r"[^a-z0-9]+", "", lowered)
        return cleaned

    def _get_priority(self, source: str) -> int:
        """Get numerical precedence for a provider source name."""
        return PROVIDER_PRIORITY.get(source.lower().strip(), 0)

    def _load_provider_games(self, provider_key: str) -> list[Game]:
        """Execute a single provider and retrieve its games safely."""
        # 1. Check custom providers
        if provider_key in self.custom_providers:
            provider = self.custom_providers[provider_key]
            try:
                if hasattr(provider, "get_games") and callable(provider.get_games):
                    return provider.get_games()
                if callable(provider):
                    return provider()
            except Exception:
                return []

        # 2. Built-in providers
        try:
            if provider_key == "steam":
                from gamedeck.providers.steam import get_games as steam_get_games

                return steam_get_games()

            if provider_key == "lutris":
                from gamedeck.providers.lutris import get_games as lutris_get_games

                return lutris_get_games()

            if provider_key == "filesystem":
                from gamedeck.providers.filesystem import get_games as fs_get_games

                return fs_get_games()

            if provider_key == "heroic":
                try:
                    from gamedeck.providers.heroic import get_games as heroic_get_games

                    return heroic_get_games()
                except (ImportError, AttributeError):
                    return []

            if provider_key == "native":
                try:
                    from gamedeck.providers.native import get_games as native_get_games

                    return native_get_games()
                except (ImportError, AttributeError):
                    return []
        except Exception:
            return []

        return []


def get_all_games(enabled_providers: list[str] | None = None) -> list[Game]:
    """Retrieve all discovered and deduplicated games across enabled providers.

    Args:
        enabled_providers: Optional list of provider names to query.

    Returns:
        A sorted list of Game model instances.
    """
    manager = ProviderManager(
        enabled_providers=enabled_providers
        if enabled_providers is not None
        else ["steam", "heroic", "lutris", "native", "filesystem"]
    )
    return manager.get_games()
