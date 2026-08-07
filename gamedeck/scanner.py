"""Game library scanner module for GameDeck."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from gamedeck.artwork import ArtworkCache
from gamedeck.database import MetadataCache
from gamedeck.models import Game
from gamedeck.provider_manager import ProviderManager, sort_games_with_recents

__all__ = ["Scanner", "scan_games"]

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Scanner:
    """Orchestrates scanning for games across all registered library providers.

    Automatically enriches discovered games with cached metadata (icons, logos, heroes,
    covers, favorites, play counts, and last played timestamps) via the SQLite database
    and local artwork cache, and sorts games by Favorites -> Recently Played -> Alphabetical.

    Attributes:
        provider_manager: ProviderManager instance configured for game discovery.
        metadata_cache: MetadataCache instance for SQLite persistence and enrichment.
        artwork_cache: ArtworkCache instance for local image and artwork resolution.
    """

    provider_manager: ProviderManager = field(default_factory=ProviderManager)
    metadata_cache: MetadataCache = field(default_factory=MetadataCache)
    artwork_cache: ArtworkCache = field(default_factory=ArtworkCache)

    def scan(self) -> list[Game]:
        """Scan all configured providers, sync with metadata cache, resolve artwork, and return sorted games.

        Returns:
            A sorted list of discovered and metadata/artwork-enriched Game model instances.
        """
        start_time = time.perf_counter()
        logger.debug("Starting game library scan across enabled providers: %s", self.provider_manager.enabled_providers)

        raw_games = self.provider_manager.get_games()

        # Step 1: Synchronize and enrich with SQLite metadata cache (favorites, last_played, launch_count)
        synced_games = self.metadata_cache.sync_all(raw_games)

        # Step 2: Enrich with local artwork cache (non-blocking fallback to application icons)
        for game in synced_games:
            self.artwork_cache.resolve_artwork(game)

        # Step 3: Re-sort games with the newly synced metadata (Favorites -> Recently Played -> Alphabetical)
        recent_limit = self.provider_manager.recent_limit
        sorted_games = sort_games_with_recents(synced_games, recent_limit=recent_limit)

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        logger.info(
            "Scan, metadata sync, and artwork resolution completed in %.1fms. Total games available: %d",
            elapsed_ms,
            len(sorted_games),
        )
        return sorted_games

    def get_games(self) -> list[Game]:
        """Alias for scan."""
        return self.scan()


def scan_games(
    enabled_providers: list[str] | None = None,
    metadata_cache: MetadataCache | None = None,
    artwork_cache: ArtworkCache | None = None,
    recent_limit: int = 5,
) -> list[Game]:
    """Scan and return all games using the default or specified providers.

    Args:
        enabled_providers: Optional list of provider identifiers to enable.
        metadata_cache: Optional custom MetadataCache instance.
        artwork_cache: Optional custom ArtworkCache instance.
        recent_limit: Maximum number of recently played games to prioritize.

    Returns:
        A sorted list of Game instances.
    """
    manager = ProviderManager(
        enabled_providers=enabled_providers
        if enabled_providers is not None
        else ["steam", "heroic", "lutris", "native", "filesystem"],
        recent_limit=recent_limit,
    )
    scanner = Scanner(
        provider_manager=manager,
        metadata_cache=metadata_cache if metadata_cache is not None else MetadataCache(),
        artwork_cache=artwork_cache if artwork_cache is not None else ArtworkCache(),
    )
    return scanner.scan()
