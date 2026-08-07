"""Artwork cache and asset resolution manager for GameDeck."""

from __future__ import annotations

import concurrent.futures
import logging
import os
import shutil
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gamedeck.models import Game

__all__ = [
    "ArtworkCache",
    "get_default_artwork_cache_dir",
]

logger = logging.getLogger(__name__)

ARTWORK_TYPES: frozenset[str] = frozenset({"icons", "logos", "heroes", "covers"})


def get_default_artwork_cache_dir() -> Path:
    """Return standard directory path for caching artwork (~/.cache/gamedeck/artwork)."""
    home = Path.home()
    xdg_cache = Path(os.environ.get("XDG_CACHE_HOME", home / ".cache"))
    return xdg_cache / "gamedeck" / "artwork"


@dataclass(slots=True)
class ArtworkCache:
    """Local filesystem artwork cache supporting icons, logos, heroes, and covers.

    Provides non-blocking asset discovery, local caching, fallback resolution
    to application icons, and asynchronous background fetching.

    Attributes:
        cache_dir: Root cache directory for local artwork storage.
        max_workers: Number of background worker threads for non-blocking downloads.
    """

    cache_dir: Path = field(default_factory=get_default_artwork_cache_dir)
    max_workers: int = 2
    _executor: concurrent.futures.ThreadPoolExecutor = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """Initialize cache subdirectories and background thread pool."""
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=self.max_workers,
            thread_name_prefix="ArtworkFetcher",
        )
        self._init_directories()

    def _init_directories(self) -> None:
        """Create artwork subdirectories for icons, logos, heroes, and covers."""
        for art_type in ARTWORK_TYPES:
            (self.cache_dir / art_type).mkdir(parents=True, exist_ok=True)

    def get_artwork(self, game_id: str, art_type: str) -> Path | None:
        """Retrieve local cached artwork file path for a game if it exists.

        Args:
            game_id: Unique game identifier.
            art_type: Category ('icons', 'logos', 'heroes', 'covers').

        Returns:
            Path to the cached image file, or None if not cached locally.
        """
        category = art_type.lower().strip()
        if not category.endswith("s") and f"{category}s" in ARTWORK_TYPES:
            category = f"{category}s"

        target_dir = self.cache_dir / category
        if not target_dir.is_dir():
            return None

        # Check supported image file extensions
        for ext in (".jpg", ".png", ".webp", ".jpeg", ".svg", ".ico"):
            candidate = target_dir / f"{game_id}{ext}"
            if candidate.is_file() and candidate.stat().st_size > 0:
                return candidate

        return None

    def store_artwork(
        self,
        game_id: str,
        art_type: str,
        source: Path | bytes | str,
        ext: str = ".jpg",
    ) -> Path:
        """Store or copy artwork into the local cache directory.

        Args:
            game_id: Unique game identifier.
            art_type: Category ('icons', 'logos', 'heroes', 'covers').
            source: Path to existing file on disk, raw image bytes, or URL.
            ext: Desired file extension (default '.jpg').

        Returns:
            Path to the saved cache file.
        """
        category = art_type.lower().strip()
        if not category.endswith("s") and f"{category}s" in ARTWORK_TYPES:
            category = f"{category}s"

        target_dir = self.cache_dir / category
        target_dir.mkdir(parents=True, exist_ok=True)

        if not ext.startswith("."):
            ext = f".{ext}"

        dest_file = target_dir / f"{game_id}{ext}"

        if isinstance(source, Path) or (isinstance(source, str) and not source.startswith("http")):
            src_path = Path(source)
            if src_path.is_file():
                shutil.copyfile(src_path, dest_file)
                logger.debug("Cached artwork copied to '%s'", dest_file)
                return dest_file

        if isinstance(source, bytes):
            with dest_file.open("wb") as f:
                f.write(source)
            logger.debug("Cached artwork written (%d bytes) to '%s'", len(source), dest_file)
            return dest_file

        return dest_file

    def resolve_artwork(self, game: Game) -> Game:
        """Enrich a Game model with cached icons, logos, heroes, and covers with graceful fallbacks.

        If a specific artwork type is unavailable, it gracefully falls back in hierarchy:
            - logo: cached logo -> game.logo -> cached icon -> game.icon
            - hero: cached hero -> game.hero -> cached cover -> game.cover -> game.icon
            - cover: cached cover -> game.cover -> cached hero -> game.hero -> game.icon
            - icon: cached icon -> game.icon

        Args:
            game: Game model instance.

        Returns:
            The enriched Game instance with resolved artwork paths.
        """
        cached_icon = self.get_artwork(game.id, "icons")
        cached_logo = self.get_artwork(game.id, "logos")
        cached_hero = self.get_artwork(game.id, "heroes")
        cached_cover = self.get_artwork(game.id, "covers")

        # Resolve icon
        if game.icon is None and cached_icon is not None:
            game.icon = cached_icon

        # Resolve logo (falling back to icon if missing)
        if game.logo is None:
            game.logo = cached_logo or game.icon

        # Resolve hero (falling back to cover then icon if missing)
        if game.hero is None:
            game.hero = cached_hero or cached_cover or game.cover or game.icon

        # Resolve cover (falling back to hero then icon if missing)
        if game.cover is None:
            game.cover = cached_cover or cached_hero or game.hero or game.icon

        return game

    def fetch_async(
        self,
        game_id: str,
        art_type: str,
        url: str,
        timeout: float = 3.0,
    ) -> None:
        """Download artwork in a non-blocking background daemon thread without delaying startup.

        Args:
            game_id: Unique game identifier.
            art_type: Category ('icons', 'logos', 'heroes', 'covers').
            url: Remote HTTP/HTTPS URL of the artwork image.
            timeout: Network request timeout in seconds.
        """
        if not url or not url.startswith("http"):
            return

        # Do not re-download if already cached locally
        if self.get_artwork(game_id, art_type) is not None:
            return

        def _download_task() -> None:
            try:
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "GameDeck/0.1.0 (Linux; SteamDeck)"},
                )
                with urllib.request.urlopen(req, timeout=timeout) as response:
                    content_type = response.headers.get("Content-Type", "")
                    ext = ".png" if "png" in content_type else ".jpg"
                    data = response.read()
                    if data:
                        self.store_artwork(game_id, art_type, data, ext=ext)
                        logger.info("Background downloaded %s for game '%s'", art_type, game_id)
            except Exception as err:
                logger.debug("Non-critical background artwork fetch failed for '%s': %s", game_id, err)

        self._executor.submit(_download_task)
