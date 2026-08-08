"""Dynamic Collections system for GameDeck backed by SQLite persistence."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar

from gamedeck.database import MetadataCache
from gamedeck.models import Game

__all__ = [
    "GameCollection",
    "BaseCollectionGenerator",
    "FavoritesCollectionGenerator",
    "RecentlyPlayedCollectionGenerator",
    "RecentlyAddedCollectionGenerator",
    "InstalledCollectionGenerator",
    "SteamCollectionGenerator",
    "LutrisCollectionGenerator",
    "HeroicCollectionGenerator",
    "NativeCollectionGenerator",
    "FilesystemCollectionGenerator",
    "WineCollectionGenerator",
    "HiddenCollectionGenerator",
    "LinuxNativeCollectionGenerator",
    "ControllerCollectionGenerator",
    "CollectionManager",
    "get_all_collections",
]

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class GameCollection:
    """Represents a discrete named grouping of games.

    Attributes:
        id: Unique identifier for the collection (e.g., 'favorites', 'recent', 'custom_rpg').
        name: Clean display name (e.g., 'Favorites', 'Recently Played', 'Steam').
        icon: Display icon symbol (e.g., '⭐', '🕒', '💾', '📁', '🎮').
        description: Brief description of the collection filter or purpose.
        is_dynamic: True for auto-generated query collections, False for user custom lists.
        games: List of matching Game instances.
    """

    id: str
    name: str
    icon: str = "📁"
    description: str = ""
    is_dynamic: bool = True
    games: list[Game] = field(default_factory=list)

    def count(self) -> int:
        """Return total number of games in this collection."""
        return len(self.games)

    @property
    def display_label(self) -> str:
        """Formatted header text for UI menus."""
        return f"{self.icon}  {self.name} ({len(self.games)})"


class BaseCollectionGenerator(ABC):
    """Abstract base for dynamic collection generators."""

    #: Unique collection identifier.
    collection_id: str

    #: Human-readable collection name.
    name: str

    #: Glyph icon symbol.
    icon: str

    #: Description.
    description: str

    @abstractmethod
    def generate(self, all_games: list[Game], metadata_cache: MetadataCache) -> GameCollection:
        """Generate and filter games into a GameCollection."""


@dataclass(slots=True)
class FavoritesCollectionGenerator(BaseCollectionGenerator):
    """Generates collection of user favorited games."""

    collection_id: str = "favorites"
    name: str = "Favorites"
    icon: str = "⭐"
    description: str = "Pinned and favorited games"

    def generate(self, all_games: list[Game], metadata_cache: MetadataCache) -> GameCollection:
        favorites = [g for g in all_games if g.favorite]
        # Sort alphabetically
        favorites.sort(key=lambda g: (g.name or "").lower())
        return GameCollection(
            id=self.collection_id,
            name=self.name,
            icon=self.icon,
            description=self.description,
            is_dynamic=True,
            games=favorites,
        )


@dataclass(slots=True)
class RecentlyPlayedCollectionGenerator(BaseCollectionGenerator):
    """Generates collection of recently launched games sorted by last_played timestamp."""

    collection_id: str = "recently_played"
    name: str = "Recently Played"
    icon: str = "🕒"
    description: str = "Games sorted by newest play session"
    limit: int = 50

    def generate(self, all_games: list[Game], metadata_cache: MetadataCache) -> GameCollection:
        recent = [g for g in all_games if g.last_played]
        # Sort descending by ISO timestamp
        recent.sort(key=lambda g: g.last_played or "", reverse=True)
        return GameCollection(
            id=self.collection_id,
            name=self.name,
            icon=self.icon,
            description=self.description,
            is_dynamic=True,
            games=recent[: self.limit],
        )


@dataclass(slots=True)
class InstalledCollectionGenerator(BaseCollectionGenerator):
    """Generates collection of currently installed and playable games."""

    collection_id: str = "installed"
    name: str = "Installed"
    icon: str = "💾"
    description: str = "All currently installed games"

    def generate(self, all_games: list[Game], metadata_cache: MetadataCache) -> GameCollection:
        installed = [g for g in all_games if g.installed]
        installed.sort(key=lambda g: (g.name or "").lower())
        return GameCollection(
            id=self.collection_id,
            name=self.name,
            icon=self.icon,
            description=self.description,
            is_dynamic=True,
            games=installed,
        )


@dataclass(slots=True)
class SteamCollectionGenerator(BaseCollectionGenerator):
    """Generates collection for Steam games."""

    collection_id: str = "steam"
    name: str = "Steam"
    icon: str = "🌐"
    description: str = "Steam library games"

    def generate(self, all_games: list[Game], metadata_cache: MetadataCache) -> GameCollection:
        matches = [g for g in all_games if (g.source or "").lower() == "steam"]
        matches.sort(key=lambda g: (g.name or "").lower())
        return GameCollection(
            id=self.collection_id,
            name=self.name,
            icon=self.icon,
            description=self.description,
            is_dynamic=True,
            games=matches,
        )


@dataclass(slots=True)
class LutrisCollectionGenerator(BaseCollectionGenerator):
    """Generates collection for Lutris runners and games."""

    collection_id: str = "lutris"
    name: str = "Lutris"
    icon: str = "🍷"
    description: str = "Lutris installed games"

    def generate(self, all_games: list[Game], metadata_cache: MetadataCache) -> GameCollection:
        matches = [g for g in all_games if (g.source or "").lower() == "lutris"]
        matches.sort(key=lambda g: (g.name or "").lower())
        return GameCollection(
            id=self.collection_id,
            name=self.name,
            icon=self.icon,
            description=self.description,
            is_dynamic=True,
            games=matches,
        )


@dataclass(slots=True)
class HeroicCollectionGenerator(BaseCollectionGenerator):
    """Generates collection for Heroic Games Launcher titles."""

    collection_id: str = "heroic"
    name: str = "Heroic"
    icon: str = "🦸"
    description: str = "Heroic Games Launcher titles"

    def generate(self, all_games: list[Game], metadata_cache: MetadataCache) -> GameCollection:
        matches = [g for g in all_games if (g.source or "").lower() == "heroic"]
        matches.sort(key=lambda g: (g.name or "").lower())
        return GameCollection(
            id=self.collection_id,
            name=self.name,
            icon=self.icon,
            description=self.description,
            is_dynamic=True,
            games=matches,
        )


@dataclass(slots=True)
class NativeCollectionGenerator(BaseCollectionGenerator):
    """Generates collection for Native Linux desktop games."""

    collection_id: str = "native"
    name: str = "Native"
    icon: str = "🐧"
    description: str = "Native Linux applications and games"

    def generate(self, all_games: list[Game], metadata_cache: MetadataCache) -> GameCollection:
        matches = [g for g in all_games if (g.source or "").lower() == "native"]
        matches.sort(key=lambda g: (g.name or "").lower())
        return GameCollection(
            id=self.collection_id,
            name=self.name,
            icon=self.icon,
            description=self.description,
            is_dynamic=True,
            games=matches,
        )


@dataclass(slots=True)
class FilesystemCollectionGenerator(BaseCollectionGenerator):
    """Generates collection for custom Filesystem / Wine directory games."""

    collection_id: str = "filesystem"
    name: str = "Filesystem"
    icon: str = "📁"
    description: str = "Filesystem discovered games"

    def generate(self, all_games: list[Game], metadata_cache: MetadataCache) -> GameCollection:
        matches = [g for g in all_games if (g.source or "").lower() in ("filesystem", "wine")]
        matches.sort(key=lambda g: (g.name or "").lower())
        return GameCollection(
            id=self.collection_id,
            name=self.name,
            icon=self.icon,
            description=self.description,
            is_dynamic=True,
            games=matches,
        )


@dataclass(slots=True)
class RecentlyAddedCollectionGenerator(BaseCollectionGenerator):
    """Generates collection of recently added games sorted by date_added timestamp."""

    collection_id: str = "recently_added"
    name: str = "Recently Added"
    icon: str = "✨"
    description: str = "Games newly added to library"
    limit: int = 50

    def generate(self, all_games: list[Game], metadata_cache: MetadataCache) -> GameCollection:
        added = [g for g in all_games if g.date_added]
        added.sort(key=lambda g: g.date_added or "", reverse=True)
        return GameCollection(
            id=self.collection_id,
            name=self.name,
            icon=self.icon,
            description=self.description,
            is_dynamic=True,
            games=added[: self.limit],
        )


@dataclass(slots=True)
class WineCollectionGenerator(BaseCollectionGenerator):
    """Generates collection for games running through Wine / Proton runners."""

    collection_id: str = "wine"
    name: str = "Wine / Proton"
    icon: str = "🍷"
    description: str = "Games running under Wine or Proton compatibility layers"

    def generate(self, all_games: list[Game], metadata_cache: MetadataCache) -> GameCollection:
        matches = [
            g for g in all_games
            if (g.launcher or "").lower() in ("wine", "proton", "bottles") or (g.source or "").lower() == "wine"
        ]
        matches.sort(key=lambda g: (g.name or "").lower())
        return GameCollection(
            id=self.collection_id,
            name=self.name,
            icon=self.icon,
            description=self.description,
            is_dynamic=True,
            games=matches,
        )


@dataclass(slots=True)
class HiddenCollectionGenerator(BaseCollectionGenerator):
    """Generates collection for hidden games."""

    collection_id: str = "hidden"
    name: str = "Hidden"
    icon: str = "👁️"
    description: str = "Hidden games"

    def generate(self, all_games: list[Game], metadata_cache: MetadataCache) -> GameCollection:
        hidden_games = [g for g in all_games if getattr(g, "hidden", False)]
        hidden_games.sort(key=lambda g: (g.name or "").lower())
        return GameCollection(
            id=self.collection_id,
            name=self.name,
            icon=self.icon,
            description=self.description,
            is_dynamic=True,
            games=hidden_games,
        )


@dataclass(slots=True)
class LinuxNativeCollectionGenerator(BaseCollectionGenerator):
    """Generates collection for games natively running on Linux without compatibility layers."""

    collection_id: str = "linux_native"
    name: str = "Linux Native"
    icon: str = "🐧"
    description: str = "Games running natively on Linux without Wine or Proton"

    def generate(self, all_games: list[Game], metadata_cache: MetadataCache) -> GameCollection:
        _wine_launchers = {"wine", "proton", "bottles"}
        matches = [
            g for g in all_games
            if (
                (g.platform or "").lower() in ("linux", "linux native", "linux_native")
                or (
                    (g.source or "").lower() in ("native", "filesystem")
                    and (g.launcher or "").lower() not in _wine_launchers
                )
            )
        ]
        matches.sort(key=lambda g: (g.name or "").lower())
        return GameCollection(
            id=self.collection_id,
            name=self.name,
            icon=self.icon,
            description=self.description,
            is_dynamic=True,
            games=matches,
        )


@dataclass(slots=True)
class ControllerCollectionGenerator(BaseCollectionGenerator):
    """Generates collection for games known to have good controller support."""

    collection_id: str = "controller"
    name: str = "Controller"
    icon: str = "🎮"
    description: str = "Games with controller / gamepad support"

    #: Keywords in game metadata that signal controller support.
    _CONTROLLER_KEYWORDS: ClassVar[frozenset[str]] = frozenset(
        {"controller", "gamepad", "joystick", "steam input", "xinput", "dinput"}
    )

    def generate(self, all_games: list[Game], metadata_cache: MetadataCache) -> GameCollection:
        matches = []
        for g in all_games:
            # Check tags, notes, or platform for controller indicators
            searchable = " ".join(filter(None, [
                (g.notes or "").lower(),
                (g.platform or "").lower(),
                # Steam games have broad controller support by default
                "controller" if (g.source or "").lower() == "steam" else "",
            ]))
            if any(kw in searchable for kw in self._CONTROLLER_KEYWORDS):
                matches.append(g)
        matches.sort(key=lambda g: (g.name or "").lower())
        return GameCollection(
            id=self.collection_id,
            name=self.name,
            icon=self.icon,
            description=self.description,
            is_dynamic=True,
            games=matches,
        )


@dataclass(slots=True)
class CollectionManager:
    """Manages dynamic and custom SQLite-persisted game collections.

    Attributes:
        metadata_cache: Persistence cache instance.
        generators: List of dynamic collection generators.
    """

    metadata_cache: MetadataCache = field(default_factory=MetadataCache)
    generators: list[BaseActionProvider | BaseCollectionGenerator] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Initialize default generators and ensure collections tables exist in SQLite."""
        self._ensure_tables()
        if not self.generators:
            self.generators = [
                FavoritesCollectionGenerator(),
                RecentlyPlayedCollectionGenerator(),
                RecentlyAddedCollectionGenerator(),
                InstalledCollectionGenerator(),
                SteamCollectionGenerator(),
                LutrisCollectionGenerator(),
                HeroicCollectionGenerator(),
                NativeCollectionGenerator(),
                WineCollectionGenerator(),
                LinuxNativeCollectionGenerator(),
                ControllerCollectionGenerator(),
                FilesystemCollectionGenerator(),
                HiddenCollectionGenerator(),
            ]

    def _ensure_tables(self) -> None:
        """Create custom collections and collection membership tables in SQLite."""
        with self.metadata_cache._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS custom_collections (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    icon TEXT NOT NULL DEFAULT '📁',
                    description TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS collection_items (
                    collection_id TEXT NOT NULL,
                    game_id TEXT NOT NULL,
                    added_at TEXT NOT NULL,
                    PRIMARY KEY (collection_id, game_id),
                    FOREIGN KEY (collection_id) REFERENCES custom_collections(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_collection_items_coll ON collection_items(collection_id)"
            )

    # -------------------------------------------------------------------------
    # Dynamic Query Collections
    # -------------------------------------------------------------------------

    def get_dynamic_collections(self, all_games: list[Game]) -> list[GameCollection]:
        """Generate all built-in dynamic collections based on current game state.

        Args:
            all_games: Full list of scanned/cached Game instances.

        Returns:
            List of GameCollection instances.
        """
        collections: list[GameCollection] = []
        for gen in self.generators:
            if isinstance(gen, BaseCollectionGenerator):
                try:
                    coll = gen.generate(all_games, self.metadata_cache)
                    if coll.count() > 0:
                        collections.append(coll)
                except Exception as err:
                    logger.error("Failed to generate collection %s: %s", gen.name, err)
        return collections

    # -------------------------------------------------------------------------
    # Custom SQLite-Persisted Collections
    # -------------------------------------------------------------------------

    def create_custom_collection(
        self,
        name: str,
        icon: str = "📁",
        description: str = "",
        collection_id: str | None = None,
    ) -> str:
        """Create and persist a new custom collection in SQLite.

        Args:
            name: Display name.
            icon: Glyph icon.
            description: Description.
            collection_id: Optional slug identifier.

        Returns:
            The created collection_id.
        """
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Collection name cannot be empty.")

        cid = collection_id or clean_name.lower().replace(" ", "_").replace("-", "_")
        now = datetime.now(timezone.utc).isoformat()

        with self.metadata_cache._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO custom_collections (id, name, icon, description, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET name = excluded.name, icon = excluded.icon, description = excluded.description
                """,
                (cid, clean_name, icon, description, now),
            )
        logger.info("Created custom collection '%s' [%s]", clean_name, cid)
        return cid

    def delete_custom_collection(self, collection_id: str) -> bool:
        """Delete a custom collection and all its item associations."""
        with self.metadata_cache._get_connection() as conn:
            cursor = conn.execute("DELETE FROM custom_collections WHERE id = ?", (collection_id,))
            conn.execute("DELETE FROM collection_items WHERE collection_id = ?", (collection_id,))
            return cursor.rowcount > 0

    def add_game_to_collection(self, collection_id: str, game_id: str) -> bool:
        """Add a game to a custom collection."""
        now = datetime.now(timezone.utc).isoformat()
        with self.metadata_cache._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO collection_items (collection_id, game_id, added_at)
                VALUES (?, ?, ?)
                """,
                (collection_id, game_id, now),
            )
            return cursor.rowcount > 0

    def remove_game_from_collection(self, collection_id: str, game_id: str) -> bool:
        """Remove a game from a custom collection."""
        with self.metadata_cache._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM collection_items WHERE collection_id = ? AND game_id = ?",
                (collection_id, game_id),
            )
            return cursor.rowcount > 0

    def get_custom_collections(self, all_games: list[Game]) -> list[GameCollection]:
        """Retrieve all custom user collections from SQLite populated with Game models."""
        game_map: dict[str, Game] = {g.id: g for g in all_games if g.id}
        collections: list[GameCollection] = []

        with self.metadata_cache._get_connection() as conn:
            cursor = conn.execute(
                "SELECT id, name, icon, description FROM custom_collections ORDER BY name"
            )
            for row in cursor.fetchall():
                cid = row["id"]
                item_cursor = conn.execute(
                    "SELECT game_id FROM collection_items WHERE collection_id = ? ORDER BY added_at",
                    (cid,),
                )
                member_ids = [r["game_id"] for r in item_cursor.fetchall()]
                matched_games = [game_map[gid] for gid in member_ids if gid in game_map]

                if matched_games:
                    collections.append(
                        GameCollection(
                            id=cid,
                            name=row["name"],
                            icon=row["icon"],
                            description=row["description"] or "",
                            is_dynamic=False,
                            games=matched_games,
                        )
                    )

        return collections

    def get_all_collections(self, all_games: list[Game]) -> list[GameCollection]:
        """Return full list of dynamic and custom collections.

        Args:
            all_games: List of available Game instances.

        Returns:
            List of all dynamic and custom GameCollection instances.
        """
        all_colls: list[GameCollection] = []
        # 1. Dynamic collections (Favorites, Recently Played, Installed, Steam, Lutris, etc.)
        all_colls.extend(self.get_dynamic_collections(all_games))
        # 2. Custom SQLite collections
        all_colls.extend(self.get_custom_collections(all_games))
        return all_colls


def get_all_collections(all_games: list[Game], metadata_cache: MetadataCache | None = None) -> list[GameCollection]:
    """Convenience helper to retrieve all dynamic and custom game collections."""
    mgr = CollectionManager(metadata_cache=metadata_cache or MetadataCache())
    return mgr.get_all_collections(all_games)
