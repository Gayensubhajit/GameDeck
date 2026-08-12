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
from typing import Any, Callable

from gamedeck.events import ArtworkDownloaded, get_event_bus
from gamedeck.models import Game

__all__ = [
    "ArtworkCache",
    "get_default_artwork_cache_dir",
]

logger = logging.getLogger(__name__)

ARTWORK_TYPES: frozenset[str] = frozenset({"icons", "logos", "heroes", "covers", "capsules", "placeholders"})


def get_default_artwork_cache_dir() -> Path:
    """Return standard directory path for caching artwork (~/.cache/gamedeck/artwork)."""
    home = Path.home()
    xdg_cache = Path(os.environ.get("XDG_CACHE_HOME", home / ".cache"))
    return xdg_cache / "gamedeck" / "artwork"


@dataclass(slots=True)
class ArtworkCache:
    """Local filesystem artwork cache supporting heroes, covers, capsules, icons, logos, and placeholders.

    Provides non-blocking asset discovery, local caching, fallback resolution
    to application icons, and asynchronous background fetching with offline mode.

    Attributes:
        cache_dir: Root cache directory for local artwork storage.
        max_workers: Number of background worker threads for non-blocking downloads.
        offline_mode: When True, prevents all remote network requests.
    """

    cache_dir: Path = field(default_factory=get_default_artwork_cache_dir)
    max_workers: int = 3
    offline_mode: bool = False
    _executor: concurrent.futures.ThreadPoolExecutor = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """Initialize cache subdirectories and background thread pool."""
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=self.max_workers,
            thread_name_prefix="ArtworkPipeline",
        )
        self._init_directories()

    def _init_directories(self) -> None:
        """Create artwork subdirectories for heroes, covers, capsules, icons, logos, and placeholders."""
        for art_type in ARTWORK_TYPES:
            (self.cache_dir / art_type).mkdir(parents=True, exist_ok=True)

    def has_artwork(self, game_id: str, art_type: str) -> bool:
        """Return True if artwork for this game and category is already cached on disk."""
        return self.get_artwork(game_id, art_type) is not None

    def get_artwork(self, game_id: str, art_type: str) -> Path | None:
        """Retrieve local cached artwork file path for a game if it exists.

        Args:
            game_id: Unique game identifier.
            art_type: Category ('heroes', 'covers', 'capsules', 'icons', 'logos', 'placeholders').

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
            art_type: Category ('heroes', 'covers', 'capsules', 'icons', 'logos', 'placeholders').
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

    def generate_placeholder(self, game: Game) -> Path:
        """Generate a clean dark translucent placeholder card with game title and launcher badge.

        Never blocks UI rendering; writes an SVG placeholder card instantly.
        """
        target_dir = self.cache_dir / "placeholders"
        target_dir.mkdir(parents=True, exist_ok=True)
        dest_file = target_dir / f"{game.id}.svg"

        if dest_file.is_file() and dest_file.stat().st_size > 0:
            return dest_file

        # Clean title for SVG rendering
        safe_title = (game.name or "Game").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        launcher_badge = (game.launcher or game.source or "NATIVE").upper()
        if len(safe_title) > 22:
            safe_title = safe_title[:20] + "..."

        svg_content = f"""<svg width="300" height="450" viewBox="0 0 300 450" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="bg_grad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#182421" />
      <stop offset="100%" stop-color="#0c1412" />
    </linearGradient>
  </defs>
  <rect width="300" height="450" rx="16" fill="url(#bg_grad)" stroke="#00e699" stroke-width="2" stroke-opacity="0.3" />
  <circle cx="150" cy="180" r="48" fill="#00e699" fill-opacity="0.15" />
  <text x="150" y="192" font-family="Outfit, sans-serif" font-size="36" font-weight="bold" fill="#00e699" text-anchor="middle">🎮</text>
  <text x="150" y="275" font-family="Outfit, sans-serif" font-size="18" font-weight="bold" fill="#f0fdf4" text-anchor="middle">{safe_title}</text>
  <rect x="90" y="315" width="120" height="28" rx="6" fill="#00e699" fill-opacity="0.2" />
  <text x="150" y="334" font-family="Outfit, sans-serif" font-size="12" font-weight="bold" fill="#00e699" text-anchor="middle">{launcher_badge}</text>
</svg>"""

        try:
            dest_file.write_text(svg_content, encoding="utf-8")
        except Exception as err:
            logger.debug("Failed to write placeholder SVG for '%s': %s", game.id, err)

        return dest_file

    def resolve_artwork_with_priority(self, game: Game) -> Path | str:
        """Resolve primary artwork according to strict priority hierarchy:
        1. Hero Image
        2. Portrait Cover
        3. Capsule
        4. Executable Icon
        5. Placeholder
        """
        # 1. Hero Image
        hero = self.get_artwork(game.id, "heroes") or getattr(game, "hero", None)
        if hero and Path(hero).is_file():
            return Path(hero)

        # 2. Portrait Cover
        cover = self.get_artwork(game.id, "covers") or getattr(game, "cover", None)
        if cover and Path(cover).is_file():
            return Path(cover)

        # 3. Capsule
        capsule = self.get_artwork(game.id, "capsules")
        if capsule and Path(capsule).is_file():
            return Path(capsule)

        # 4. Executable Icon
        icon = self.get_artwork(game.id, "icons") or getattr(game, "icon", None)
        if icon and Path(icon).is_file():
            return Path(icon)

        # 5. Placeholder
        return self.generate_placeholder(game)

    def resolve_artwork(self, game: Game) -> Game:
        """Enrich a Game model with cached icons, logos, heroes, and covers with graceful fallbacks."""
        cached_icon = self.get_artwork(game.id, "icons")
        cached_logo = self.get_artwork(game.id, "logos")
        cached_hero = self.get_artwork(game.id, "heroes")
        cached_cover = self.get_artwork(game.id, "covers")

        # Resolve icon
        if game.icon is None and cached_icon is not None:
            game.icon = cached_icon

        # Resolve logo
        if game.logo is None:
            game.logo = cached_logo or game.icon

        # Resolve hero
        if game.hero is None:
            game.hero = cached_hero or cached_cover or game.cover or game.icon

        # Resolve cover
        if game.cover is None:
            game.cover = cached_cover or cached_hero or game.hero or game.icon

        return game

    def fetch_async(
        self,
        game_id: str,
        art_type: str,
        url: str,
        on_complete: Callable[[str, str, Path], None] | None = None,
        timeout: float = 3.0,
        force: bool = False,
    ) -> None:
        """Download artwork in a non-blocking background daemon thread without delaying startup.

        Args:
            game_id: Unique game identifier.
            art_type: Category ('icons', 'logos', 'heroes', 'covers', 'capsules').
            url: Remote HTTP/HTTPS URL of the artwork image.
            on_complete: Optional callback invoked with (game_id, art_type, file_path).
            timeout: Network request timeout in seconds.
            force: If True, re-download artwork even if cached locally (for metadata refresh).
        """
        if self.offline_mode or not url or not url.startswith("http"):
            return

        # Do not re-download if already cached locally, unless force=True
        if not force and self.has_artwork(game_id, art_type):
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
                        saved_path = self.store_artwork(game_id, art_type, data, ext=ext)
                        logger.info("Background downloaded %s for game '%s'", art_type, game_id)

                        # Emit EventBus event
                        try:
                            bus = get_event_bus()
                            bus.publish(ArtworkDownloaded(
                                game_id=game_id,
                                art_type=art_type,
                                file_path=str(saved_path),
                            ))
                        except Exception as event_err:
                            logger.debug("EventBus notification failed: %s", event_err)

                        if on_complete:
                            on_complete(game_id, art_type, saved_path)
            except Exception as err:
                logger.debug("Non-critical background artwork fetch failed for '%s': %s", game_id, err)

        self._executor.submit(_download_task)
