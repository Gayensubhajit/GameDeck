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

    def enrich(self, game: Game, force_refresh: bool = False) -> Game:
        """Enrich a single Game model with cached metadata and artwork assets.

        Args:
            game: The raw Game model instance returned from a provider.
            force_refresh: If True, force re-downloads artwork during metadata refresh.

        Returns:
            The enriched Game instance.
        """
        # 1. Synchronize with SQLite metadata cache (favorites, launch count, last played)
        self.metadata_cache.sync_game(game)

        # 2. Resolve artwork from local cache / fallback hierarchies
        self.resolve_artwork(game, force_refresh=force_refresh)

        return game

    def enrich_all(self, games: list[Game], force_refresh: bool = False) -> list[Game]:
        """Enrich a list of Game models with cached metadata and artwork.

        Args:
            games: List of raw Game model instances from providers.
            force_refresh: If True, force re-downloads artwork during metadata refresh.

        Returns:
            List of synchronized and artwork-enriched Game instances.
        """
        # 1. Bulk sync with SQLite
        synced_games = self.metadata_cache.sync_all(games)

        # 2. Resolve artwork for each game
        for game in synced_games:
            self.resolve_artwork(game, force_refresh=force_refresh)

        return synced_games

    def resolve_artwork(self, game: Game, force_refresh: bool = False) -> Game:
        """Resolve icon, logo, hero, and cover artwork paths for a Game following priority hierarchy:
        1 Hero Image
        2 Portrait Cover
        3 Capsule
        4 Executable Icon
        5 Placeholder

        Args:
            game: Game model instance.
            force_refresh: If True, force background fetch for newer artwork versions.

        Returns:
            The Game instance with resolved artwork attributes.
        """
        # 1. Check custom cached artwork from ArtworkCache
        cached_icon = self.artwork_cache.get_artwork(game.id, "icons")
        cached_logo = self.artwork_cache.get_artwork(game.id, "logos")
        cached_hero = self.artwork_cache.get_artwork(game.id, "heroes")
        cached_cover = self.artwork_cache.get_artwork(game.id, "covers")
        cached_capsule = self.artwork_cache.get_artwork(game.id, "capsules")

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

        # Trigger background SteamGridDB asset download (never re-download unless force_refresh=True)
        if self.steamgriddb is not None and self.steamgriddb.is_available():
            if force_refresh or game.cover is None or game.icon is None or game.logo is None or game.hero is None:
                self.steamgriddb.fetch_game_artwork_background(game, force=force_refresh)

        # Fallback hierarchy following 1-Hero, 2-Cover, 3-Capsule, 4-Icon, 5-Placeholder
        if game.hero is None:
            game.hero = cached_hero or cached_cover or game.cover or cached_capsule or game.icon
        if game.logo is None:
            game.logo = cached_logo or game.icon
        if game.cover is None:
            game.cover = cached_cover or game.hero or cached_capsule or game.icon

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

    def enrich_background(
        self,
        game_ids: list[str],
        *,
        download_artwork: bool = True,
    ) -> list[Game]:
        """Non-blocking background enrichment of a subset of games by ID.

        Designed to be called from a background thread after a scan detects
        new games. Does not block the interactive UI.

        Args:
            game_ids: List of game IDs to enrich.
            download_artwork: Whether to trigger SteamGridDB background downloads.

        Returns:
            List of enriched Game instances for the given IDs.
        """
        cached_games = self.metadata_cache.get_all_cached_games()
        target_games = [g for g in cached_games if g.id in set(game_ids)]

        for game in target_games:
            try:
                # Sync metadata from SQLite
                self.metadata_cache.sync_game(game)
                # Resolve local artwork
                self.resolve_artwork(game)
                # Queue SteamGridDB download if needed and enabled
                if (
                    download_artwork
                    and self.steamgriddb is not None
                    and self.steamgriddb.is_available()
                    and (game.cover is None or game.hero is None)
                ):
                    self.steamgriddb.fetch_game_artwork_background(game)
            except Exception as err:
                import logging as _log
                _log.getLogger(__name__).warning(
                    "enrich_background: Failed to enrich game %s: %s", game.id, err
                )

        return target_games

    def generate_thumbnails(
        self,
        games: list[Game],
        size: tuple[int, int] = (190, 280),
        *,
        force: bool = False,
    ) -> dict[str, Path]:
        """Pre-scale artwork files to thumbnail dimensions for faster grid rendering.

        Generated thumbnails are stored in the artwork cache directory under
        'thumbnails/' and reused on subsequent renders. Skips games that already
        have a cached thumbnail unless force=True.

        Args:
            games: List of Game instances to generate thumbnails for.
            size: Thumbnail dimensions as (width, height).
            force: If True, regenerate even if thumbnail already exists.

        Returns:
            Dict mapping game.id to the thumbnail Path for each successfully
            processed game.
        """
        import shutil as _shutil

        thumb_dir = Path.home() / ".cache" / "gamedeck" / "thumbnails"
        thumb_dir.mkdir(parents=True, exist_ok=True)

        results: dict[str, Path] = {}

        for game in games:
            source_art = game.cover or game.hero or game.icon
            if source_art is None:
                continue

            source_path = Path(source_art)
            if not source_path.is_file():
                continue

            thumb_name = f"{game.id}_{size[0]}x{size[1]}{source_path.suffix}"
            thumb_path = thumb_dir / thumb_name

            if thumb_path.is_file() and not force:
                results[game.id] = thumb_path
                continue

            # Use ImageMagick's convert if available (lightweight, no Python deps)
            convert_bin = _shutil.which("convert")
            if convert_bin:
                import subprocess as _sub
                try:
                    _sub.run(
                        [
                            convert_bin,
                            str(source_path),
                            "-resize", f"{size[0]}x{size[1]}^",
                            "-gravity", "center",
                            "-extent", f"{size[0]}x{size[1]}",
                            str(thumb_path),
                        ],
                        capture_output=True,
                        check=False,
                        timeout=10,
                    )
                    if thumb_path.is_file():
                        results[game.id] = thumb_path
                        continue
                except Exception:
                    pass

            # Fallback: copy source as-is (no resizing without convert)
            try:
                _shutil.copy2(source_path, thumb_path)
                results[game.id] = thumb_path
            except Exception:
                pass

        return results
