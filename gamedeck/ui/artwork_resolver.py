"""Multi-tier artwork resolver for GameDeck.

Implements a non-blocking artwork discovery hierarchy:
1. SteamGridDB Hero (game.hero or ~/.cache/gamedeck/artwork/heroes/{id}.jpg)
2. SteamGridDB Portrait / Cover (game.cover or ~/.cache/gamedeck/artwork/covers/{id}.png)
3. Steam Capsule (~/.cache/gamedeck/artwork/capsules/{id}.jpg or local Steam cache)
4. Game Icon (game.icon or ~/.cache/gamedeck/artwork/icons/{id}.png)
5. Executable Icon (extracted from binary or desktop entry)
6. Themed Fallback Placeholder (SVG/PNG fallback or desktop theme icon)
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gamedeck.artwork import ArtworkCache
from gamedeck.models import Game

logger = logging.getLogger(__name__)

# Standard fallback icon names in Linux desktop icon themes
FALLBACK_ICON: str = "applications-games"
THEME_ICONS: dict[str, str] = {
    "steam": "steam",
    "lutris": "lutris",
    "heroic": "heroic",
    "wine": "wine",
    "proton": "wine",
    "bottles": "com.usebottles.bottles",
    "gog": "gog-galaxy",
    "itch": "itch",
    "retroarch": "retroarch",
    "rpcs3": "rpcs3",
    "pcsx2": "pcsx2",
    "moonlight": "moonlight",
    "sunshine": "sunshine",
    "native": "applications-games",
    "filesystem": "applications-games",
}


@dataclass(slots=True)
class ArtworkResolver:
    """Resolves artwork paths with caching and priority fallback."""

    cache_dir: Path = field(
        default_factory=lambda: Path.home() / ".cache" / "gamedeck" / "artwork"
    )
    _thumbnail_cache: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        (self.cache_dir / "heroes").mkdir(exist_ok=True)
        (self.cache_dir / "covers").mkdir(exist_ok=True)
        (self.cache_dir / "capsules").mkdir(exist_ok=True)
        (self.cache_dir / "icons").mkdir(exist_ok=True)
        (self.cache_dir / "logos").mkdir(exist_ok=True)

    def resolve_grid_cover(self, game: Game, preferred_type: str = "portrait") -> str:
        """Resolve the best artwork for grid view display according to priority:
        1. SteamGridDB Hero
        2. SteamGridDB Portrait / Cover
        3. Steam Capsule
        4. Executable Icon
        5. Placeholder
        """
        cache_key = f"{game.id}:{preferred_type}"
        if cache_key in self._thumbnail_cache:
            cached_path = self._thumbnail_cache[cache_key]
            if not cached_path.startswith("/") or Path(cached_path).is_file():
                return cached_path

        # Check in order based on preferred artwork format
        if preferred_type in ("hero", "landscape", "carousel"):
            candidate_fns = [self.get_hero, self.get_cover, self.get_capsule, self.get_icon]
        else:
            candidate_fns = [self.get_cover, self.get_hero, self.get_capsule, self.get_icon]

        for fn in candidate_fns:
            art_path = fn(game)
            if art_path:
                self._thumbnail_cache[cache_key] = art_path
                return art_path

        if game.executable is not None:
            exe_icon = self._find_executable_icon(Path(game.executable))
            if exe_icon:
                self._thumbnail_cache[cache_key] = exe_icon
                return exe_icon

        # 5. Placeholder
        placeholder = self.get_placeholder(game)
        if placeholder:
            self._thumbnail_cache[cache_key] = placeholder
            return placeholder

        fallback = self.get_theme_icon(game)
        self._thumbnail_cache[cache_key] = fallback
        return fallback

    def get_placeholder(self, game: Game) -> str:
        """Generate or retrieve a clean dark translucent placeholder card for the game."""
        cache = ArtworkCache(cache_dir=self.cache_dir)
        ph = cache.generate_placeholder(game)
        return str(ph)

    def get_hero(self, game: Game) -> str | None:
        """Get hero banner artwork path if available."""
        if getattr(game, "hero", None):
            p = Path(game.hero)
            if p.is_file():
                return str(p)

        # Check local cache
        cached = self.cache_dir / "heroes" / f"{game.id}.jpg"
        if cached.is_file():
            return str(cached)

        cached_png = self.cache_dir / "heroes" / f"{game.id}.png"
        if cached_png.is_file():
            return str(cached_png)

        return None

    def get_cover(self, game: Game) -> str | None:
        """Get vertical portrait cover artwork path if available."""
        if getattr(game, "cover", None):
            p = Path(game.cover)
            if p.is_file():
                return str(p)

        # Check local cache
        for ext in (".png", ".jpg", ".jpeg"):
            cached = self.cache_dir / "covers" / f"{game.id}{ext}"
            if cached.is_file():
                return str(cached)

        # Check appid match
        if game.appid:
            for ext in (".png", ".jpg", ".jpeg"):
                cached = self.cache_dir / "covers" / f"{game.appid}{ext}"
                if cached.is_file():
                    return str(cached)

        return None

    def get_capsule(self, game: Game) -> str | None:
        """Get Steam capsule banner artwork path if available."""
        for ext in (".jpg", ".png"):
            cached = self.cache_dir / "capsules" / f"{game.id}{ext}"
            if cached.is_file():
                return str(cached)

        if game.appid and (game.source == "steam" or game.id.startswith("steam_")):
            home = Path.home()
            steam_cached = home / ".steam" / "steam" / "appcache" / "librarycache" / f"{game.appid}_header.jpg"
            if steam_cached.is_file():
                return str(steam_cached)

        return None

    def get_icon(self, game: Game) -> str | None:
        """Get square/icon artwork path if available."""
        if getattr(game, "icon", None):
            p = Path(game.icon)
            if p.is_file():
                return str(p)

        # Check local cache
        for ext in (".png", ".jpg", ".ico", ".svg"):
            cached = self.cache_dir / "icons" / f"{game.id}{ext}"
            if cached.is_file():
                return str(cached)

        return None

    def _find_executable_icon(self, executable: Path) -> str | None:
        """Search surrounding game folders for local icons."""
        try:
            parent = executable.parent if executable.is_file() else executable
            candidates = [
                parent / "icon.png",
                parent / "icon.ico",
                parent / "logo.png",
                parent / "cover.png",
                parent / f"{executable.stem}.png",
                parent / f"{executable.stem}.ico",
                parent.parent / "icon.png",
                parent.parent / "icon.ico",
            ]
            for c in candidates:
                if c.is_file():
                    return str(c)
        except Exception as err:
            logger.debug("Error searching executable icons: %s", err)
        return None

    def get_theme_icon(self, game: Game) -> str:
        """Get desktop theme icon fallback string."""
        source = (game.source or "").lower().strip()
        launcher = (game.launcher or "").lower().strip()

        if launcher in THEME_ICONS and launcher not in ("wine", "native", "filesystem"):
            return THEME_ICONS[launcher]
        if source in THEME_ICONS and source not in ("filesystem", "native"):
            return THEME_ICONS[source]
        if launcher in THEME_ICONS:
            return THEME_ICONS[launcher]
        if source in THEME_ICONS:
            return THEME_ICONS[source]
        return FALLBACK_ICON
