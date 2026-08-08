"""Game library scanner for GameDeck.

The ``Scanner`` class orchestrates provider scanning, metadata enrichment,
and sort ordering.  ``scan_games()`` is a convenience function for simple
scripts that do not need to manage the full application stack.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from gamedeck.artwork import ArtworkCache
from gamedeck.database import MetadataCache
from gamedeck.metadata_manager import MetadataManager
from gamedeck.models import Game
from gamedeck.provider_manager import ProviderManager, sort_games_with_recents

__all__ = ["Scanner", "scan_games"]

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Scanner:
    """Orchestrates scanning for games across all registered library providers.

    Automatically enriches discovered games with cached metadata and artwork via
    the central MetadataManager, and sorts games by Favorites -> Recently Played -> Alphabetical.

    Attributes:
        provider_manager: ProviderManager instance configured for game discovery.
        metadata_manager: MetadataManager instance owning metadata persistence and artwork.
    """

    provider_manager: ProviderManager = field(default_factory=ProviderManager)
    metadata_manager: MetadataManager = field(default_factory=MetadataManager)

    @property
    def metadata_cache(self) -> MetadataCache:
        """Backwards-compatibility accessor for the SQLite metadata cache."""
        return self.metadata_manager.metadata_cache

    @property
    def artwork_cache(self) -> ArtworkCache:
        """Backwards-compatibility accessor for the local artwork cache."""
        return self.metadata_manager.artwork_cache

    def scan(self) -> list[Game]:
        """Scan all configured providers, enrich via MetadataManager, and return sorted games.

        Returns:
            A sorted list of discovered and metadata/artwork-enriched Game model instances.
        """
        start_time = time.perf_counter()
        logger.debug(
            "Starting game library scan across enabled providers: %s",
            self.provider_manager.enabled_providers,
        )

        raw_games = self.provider_manager.get_games()

        # Enrich with MetadataManager (SQLite stats + artwork caching/discovery)
        enriched_games = self.metadata_manager.enrich_all(raw_games)

        # Re-sort games with the newly synced metadata (Favorites -> Recently Played -> Alphabetical)
        recent_limit = self.provider_manager.recent_limit
        sorted_games = sort_games_with_recents(enriched_games, recent_limit=recent_limit)

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        logger.info(
            "Scan, metadata sync, and artwork resolution completed in %.1fms. Total games available: %d",
            elapsed_ms,
            len(sorted_games),
        )
        return sorted_games


def scan_games(
    enabled_providers: list[str] | None = None,
    metadata_manager: MetadataManager | None = None,
    metadata_cache: MetadataCache | None = None,
    artwork_cache: ArtworkCache | None = None,
    recent_limit: int = 5,
) -> list[Game]:
    """Scan and return all games using the default or specified providers.

    Args:
        enabled_providers: Optional list of provider identifiers to enable.
        metadata_manager: Optional custom MetadataManager instance.
        metadata_cache: Optional custom MetadataCache instance (creates MetadataManager).
        artwork_cache: Optional custom ArtworkCache instance (creates MetadataManager).
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

    if metadata_manager is None:
        meta_cache = metadata_cache if metadata_cache is not None else MetadataCache()
        art_cache = artwork_cache if artwork_cache is not None else ArtworkCache()
        metadata_manager = MetadataManager(
            metadata_cache=meta_cache,
            artwork_cache=art_cache,
        )

    scanner = Scanner(
        provider_manager=manager,
        metadata_manager=metadata_manager,
    )
    return scanner.scan()
