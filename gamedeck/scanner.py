"""Game library scanner module for GameDeck."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from gamedeck.models import Game
from gamedeck.provider_manager import ProviderManager

__all__ = ["Scanner", "scan_games"]

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Scanner:
    """Orchestrates scanning for games across all registered library providers.

    Attributes:
        provider_manager: ProviderManager instance configured for game discovery.
    """

    provider_manager: ProviderManager = field(default_factory=ProviderManager)

    def scan(self) -> list[Game]:
        """Scan all configured providers and return a deduplicated, sorted list of games.

        Returns:
            A sorted list of discovered Game model instances.
        """
        start_time = time.perf_counter()
        logger.debug("Starting game library scan across enabled providers: %s", self.provider_manager.enabled_providers)

        games = self.provider_manager.get_games()

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        logger.info("Scan completed in %.1fms. Total games available: %d", elapsed_ms, len(games))
        return games

    def get_games(self) -> list[Game]:
        """Alias for scan."""
        return self.scan()


def scan_games(enabled_providers: list[str] | None = None) -> list[Game]:
    """Scan and return all games using the default or specified providers.

    Args:
        enabled_providers: Optional list of provider identifiers to enable.

    Returns:
        A sorted list of Game instances.
    """
    manager = ProviderManager(
        enabled_providers=enabled_providers
        if enabled_providers is not None
        else ["steam", "heroic", "lutris", "native", "filesystem"]
    )
    scanner = Scanner(provider_manager=manager)
    return scanner.scan()
