"""Metadata and artwork manager orchestrating persistence, artwork caching, and non-blocking enrichment."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gamedeck.artwork import ArtworkCache, get_default_artwork_cache_dir
from gamedeck.database import GameMetadata, MetadataCache
from gamedeck.models import Game
from gamedeck.steamgriddb import SteamGridDBClient

__all__ = [
    "MetadataManager",
]

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class MetadataManager:
    """Central metadata and artwork management service for GameDeck.

    Owns:
        - Cached metadata (favorites, last_played, launch_count via SQLite MetadataCache)
        - Artwork assets (icons, logos, heroes, covers via ArtworkCache)
        - Non-blocking asynchronous artwork resolution and lazy loading.

    Attributes:
        metadata_cache: Persistence cache for user metadata.
        artwork_cache: Local filesystem and async cache for artwork assets.
    """

    metadata_cache: MetadataCache = field(default_factory=MetadataCache)
    artwork_cache: ArtworkCache = field(default_factory=ArtworkCache)
    steamgriddb: SteamGridDBClient | None = None

    def __post_init__(self) -> None:
        """Initialize SteamGridDB client sharing the same artwork cache."""
        if self.steamgriddb is None:
            self.steamgriddb = SteamGridDBClient(artwork_cache=self.artwork_cache)

    def enrich(self, game: Game) -> Game:
        """Enrich a single Game model with cached metadata and artwork assets.

        Args:
            game: The raw Game model instance returned from a provider.

        Returns:
            The enriched Game instance.
        """
        # 1. Synchronize with SQLite metadata cache (favorites, launch count, last played)
        self.metadata_cache.sync_game(game)

        # 2. Resolve artwork from local cache / fallback hierarchies
        self.resolve_artwork(game)

        return game

    def enrich_all(self, games: list[Game]) -> list[Game]:
        """Enrich a list of Game models with cached metadata and artwork.

        Args:
            games: List of raw Game model instances from providers.

        Returns:
            List of synchronized and artwork-enriched Game instances.
        """
        # 1. Bulk sync with SQLite
        synced_games = self.metadata_cache.sync_all(games)

        # 2. Resolve artwork for each game
        for game in synced_games:
            self.resolve_artwork(game)

        return synced_games

    def resolve_artwork(self, game: Game) -> Game:
        """Resolve icon, logo, hero, and cover artwork paths for a Game.

        Strict Icon Priority:
        1. Cached custom icon (if downloaded by ArtworkCache / ArtworkManager)
        2. Native application icon from the provider (Steam, Lutris, Heroic, .desktop)
        3. Executable icon (when available)
        4. Generic fallback icon

        Guarantees:
        - Never replaces a valid native provider icon with a generic fallback.
        - Preserves existing icon fields on Game models returned by providers.
        - Enriches missing artwork fields without removing existing ones.

        Args:
            game: Game model instance.

        Returns:
            The Game instance with resolved artwork attributes.
        """
        # 1. Check custom cached artwork from ArtworkCache
        cached_icon = self.artwork_cache.get_artwork(game.id, "icons")
        cached_logo = self.artwork_cache.get_artwork(game.id, "logos")
        cached_hero = self.artwork_cache.get_artwork(game.id, "heroes")
        cached_cover = self.artwork_cache.get_artwork(game.id, "covers")

        # Icon priority 1: Custom cached icon overrides default provider icon if present
        if cached_icon is not None:
            game.icon = cached_icon

        # Icon priority 2 & 3: If still None, discover platform/executable icon
        if game.icon is None:
            discovered_icon = self._discover_platform_icon(game)
            if discovered_icon is not None:
                game.icon = discovered_icon

        # Cover resolution
        if cached_cover is not None:
            game.cover = cached_cover
        elif game.cover is None:
            discovered_cover = self._discover_platform_cover(game)
            if discovered_cover is not None:
                game.cover = discovered_cover

        # Trigger background SteamGridDB asset download if any art is missing
        if self.steamgriddb is not None and self.steamgriddb.is_available():
            if game.cover is None or game.icon is None or game.logo is None or game.hero is None:
                self.steamgriddb.fetch_game_artwork_background(game)

        # Fallback hierarchy for logo, hero, cover while preserving icon integrity
        if game.logo is None:
            game.logo = cached_logo or game.icon
        if game.hero is None:
            game.hero = cached_hero or game.cover or game.icon
        if game.cover is None:
            game.cover = game.hero or game.icon

        return game

    def load_artwork_lazy(self, game: Game, art_type: str) -> Path | None:
        """Lazy-load and return the path to a specific artwork type for a game.

        Args:
            game: Game model instance.
            art_type: 'icons', 'logos', 'heroes', or 'covers'.

        Returns:
            Path to the artwork file if available, else None.
        """
        cached = self.artwork_cache.get_artwork(game.id, art_type)
        if cached is not None:
            return cached

        # Re-run resolution if not currently present
        self.resolve_artwork(game)

        norm_type = art_type.lower().rstrip("s")
        if norm_type == "icon":
            return game.icon
        elif norm_type == "logo":
            return game.logo
        elif norm_type == "hero":
            return game.hero
        elif norm_type == "cover":
            return game.cover
        return None

    def fetch_artwork_async(self, game_id: str, art_type: str, url: str) -> None:
        """Queue a non-blocking background artwork download without delaying the UI.

        Args:
            game_id: Unique game identifier.
            art_type: Artwork category ('icons', 'logos', 'heroes', 'covers').
            url: Remote image URL.
        """
        self.artwork_cache.fetch_async(game_id=game_id, art_type=art_type, url=url)

    def record_launch(self, game_id: str) -> None:
        """Record game launch timestamp and increment launch count in metadata cache."""
        self.metadata_cache.record_launch(game_id)

    def toggle_favorite(self, game_id: str) -> bool:
        """Toggle favorite status for a game in the metadata cache."""
        return self.metadata_cache.toggle_favorite(game_id)

    def get_metadata(self, game_id: str) -> GameMetadata | None:
        """Retrieve stored metadata record for a game."""
        return self.metadata_cache.get_metadata(game_id)

    # ------------------------------------------------------------------
    # Private Platform Asset Discovery
    # ------------------------------------------------------------------

    def _discover_platform_icon(self, game: Game) -> Path | None:
        """Discover icon from system/platform directories (Steam, Lutris, Desktop)."""
        source = (game.source or "").lower().strip()
        appid = game.appid or ""
        home = Path.home()
        xdg_data = Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share"))

        if source == "steam" and appid:
            candidates = [
                xdg_data / "icons" / "hicolor" / "128x128" / "apps" / f"steam_icon_{appid}.png",
                xdg_data / "icons" / "hicolor" / "256x256" / "apps" / f"steam_icon_{appid}.png",
                xdg_data / "icons" / "hicolor" / "scalable" / "apps" / f"steam_icon_{appid}.svg",
                home / ".local" / "share" / "icons" / "hicolor" / "128x128" / "apps" / f"steam_icon_{appid}.png",
                Path("/usr/share/icons/hicolor/128x128/apps") / f"steam_icon_{appid}.png",
                xdg_data / "Steam" / "appcache" / "librarycache" / appid / f"{appid}_icon.jpg",
                xdg_data / "Steam" / "appcache" / "librarycache" / appid / "icon.png",
                home / ".steam" / "steam" / "appcache" / "librarycache" / appid / f"{appid}_icon.jpg",
            ]
            for c in candidates:
                if c.is_file() and c.stat().st_size > 0:
                    return c

        elif source == "lutris" and appid:
            slug = appid
            candidates = [
                xdg_data / "icons" / "hicolor" / "128x128" / "apps" / f"lutris_{slug}.png",
                xdg_data / "icons" / "hicolor" / "scalable" / "apps" / f"lutris_{slug}.svg",
                home / ".local" / "share" / "icons" / "hicolor" / "128x128" / "apps" / f"lutris_{slug}.png",
                xdg_data / "lutris" / "icons" / f"{slug}.png",
                home / ".cache" / "lutris" / "icons" / f"{slug}.png",
            ]
            for c in candidates:
                if c.is_file() and c.stat().st_size > 0:
                    return c

        elif source == "native" and appid:
            # Check system and user hicolor icon themes
            icon_dirs = [
                xdg_data / "icons" / "hicolor" / "128x128" / "apps",
                xdg_data / "icons" / "hicolor" / "256x256" / "apps",
                xdg_data / "icons" / "hicolor" / "scalable" / "apps",
                xdg_data / "icons" / "hicolor" / "64x64" / "apps",
                xdg_data / "icons" / "hicolor" / "48x48" / "apps",
                home / ".local" / "share" / "icons" / "hicolor" / "128x128" / "apps",
                Path("/usr/share/icons/hicolor/128x128/apps"),
                Path("/usr/share/icons/hicolor/64x64/apps"),
                Path("/usr/share/icons/hicolor/48x48/apps"),
                Path("/usr/share/icons/hicolor/scalable/apps"),
                Path("/usr/share/pixmaps"),
            ]
            for d in icon_dirs:
                if not d.is_dir():
                    continue
                for ext in (".png", ".svg", ".xpm"):
                    candidate = d / f"{appid}{ext}"
                    if candidate.is_file() and candidate.stat().st_size > 0:
                        return candidate

        elif game.executable is not None:
            exe_path = Path(game.executable)
            game_dir = exe_path if exe_path.is_dir() else exe_path.parent
            if game_dir.is_dir():
                for ext in (".png", ".ico", ".svg"):
                    for name in ("icon", "app"):
                        candidate = game_dir / f"{name}{ext}"
                        if candidate.is_file() and candidate.stat().st_size > 0:
                            return candidate

        return None

    def _discover_platform_cover(self, game: Game) -> Path | None:
        """Discover cover art from system/platform directories (Steam librarycache, Lutris coverart)."""
        source = (game.source or "").lower().strip()
        appid = game.appid or ""
        home = Path.home()
        xdg_data = Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share"))

        if source == "steam" and appid:
            candidates = [
                xdg_data / "Steam" / "appcache" / "librarycache" / appid / "library_600x900.jpg",
                xdg_data / "Steam" / "appcache" / "librarycache" / appid / "library_600x900_2x.jpg",
                xdg_data / "Steam" / "appcache" / "librarycache" / appid / "library_capsule.jpg",
                home / ".steam" / "steam" / "appcache" / "librarycache" / appid / "library_600x900.jpg",
            ]
            for c in candidates:
                if c.is_file() and c.stat().st_size > 0:
                    return c

        elif source == "lutris" and appid:
            slug = appid
            candidates = [
                xdg_data / "lutris" / "coverart" / f"{slug}.jpg",
                xdg_data / "lutris" / "coverart" / f"{slug}.png",
                xdg_data / "lutris" / "banners" / f"{slug}.jpg",
                home / ".cache" / "lutris" / "coverart" / f"{slug}.jpg",
            ]
            for c in candidates:
                if c.is_file() and c.stat().st_size > 0:
                    return c

        return None
