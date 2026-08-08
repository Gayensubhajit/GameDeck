"""Public Python API for GameDeck allowing third-party tools to query games, metadata, collections, profiles, and statistics."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from gamedeck.collections import CollectionManager, GameCollection
from gamedeck.database import MetadataCache
from gamedeck.details import GameDetails, GameDetailsProvider
from gamedeck.models import Game
from gamedeck.profiles import LaunchProfile, ProfileManager
from gamedeck.saves import SaveBackup, SaveManager
from gamedeck.screenshots import Screenshot, ScreenshotManager
from gamedeck.stats import LibraryStats, LibraryStatsProvider

__all__ = [
    "GameDeckAPI",
    "get_api",
]

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class GameDeckAPI:
    """Public Python API interface for third-party integrations."""

    metadata_cache: MetadataCache = field(default_factory=MetadataCache)

    def get_games(self) -> list[Game]:
        """Query and return all cached Game objects from SQLite."""
        return self.metadata_cache.get_all_cached_games()

    def get_metadata(self, game_or_id: Game | str) -> GameDetails | None:
        """Query detailed GameDetails for a given Game instance or game ID."""
        provider = GameDetailsProvider(metadata_cache=self.metadata_cache)
        return provider.get_details(game_or_id)

    def get_collections(self) -> list[GameCollection]:
        """Query all dynamic and custom collections."""
        games = self.get_games()
        manager = CollectionManager(metadata_cache=self.metadata_cache)
        return manager.get_all_collections(games)

    def get_profiles(self, game_or_id: Game | str) -> list[LaunchProfile]:
        """Query launch profiles for a specific game."""
        games = self.get_games()
        target_id = game_or_id.id if isinstance(game_or_id, Game) else str(game_or_id)
        matched = [g for g in games if g.id == target_id]
        if not matched:
            return []
        prof_mgr = ProfileManager(metadata_cache=self.metadata_cache)
        return prof_mgr.get_profiles(matched[0])

    def get_stats(self) -> LibraryStats:
        """Query aggregate library statistics."""
        provider = LibraryStatsProvider(metadata_cache=self.metadata_cache)
        return provider.calculate_stats()

    def get_saves(self, game_id: str) -> list[SaveBackup]:
        """Query save game backups for a specific game."""
        save_mgr = SaveManager(metadata_cache=self.metadata_cache)
        return save_mgr.list_backups(game_id)

    def get_screenshots(self, game: Game) -> list[Screenshot]:
        """Query discovered screenshots for a specific game."""
        sc_mgr = ScreenshotManager()
        return sc_mgr.discover_screenshots(game)


def get_api() -> GameDeckAPI:
    """Convenience factory returning a GameDeckAPI instance."""
    return GameDeckAPI()
