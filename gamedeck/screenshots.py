"""Screenshot Manager for GameDeck enabling screenshot discovery, metadata indexing, and previews."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from gamedeck.models import Game

__all__ = [
    "Screenshot",
    "ScreenshotManager",
]

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class Screenshot:
    """Represents a discovered game screenshot image."""

    id: str
    game_id: str
    file_path: Path
    created_at: str
    size_bytes: int


@dataclass(slots=True)
class ScreenshotManager:
    """Discovers and manages game screenshots across Steam, Lutris, and custom folders."""

    def discover_screenshots(self, game: Game) -> list[Screenshot]:
        """Discover screenshots for a game across standard location paths."""
        screenshots: list[Screenshot] = []
        home = Path.home()
        candidates: list[Path] = []

        # 1. Steam screenshots directory
        if game.source == "steam" and game.appid:
            steam_udata = home / ".local" / "share" / "Steam" / "userdata"
            if steam_udata.is_dir():
                for udir in steam_udata.iterdir():
                    sc_dir = udir / "760" / "remote" / game.appid / "screenshots"
                    if sc_dir.is_dir():
                        candidates.append(sc_dir)

        # 2. Custom GameDeck screenshots directory (~/.local/share/gamedeck/screenshots/<game_id>)
        custom_dir = home / ".local" / "share" / "gamedeck" / "screenshots" / game.id
        if custom_dir.is_dir():
            candidates.append(custom_dir)

        # Enumerate images
        for cdir in candidates:
            for ext in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
                for img_file in cdir.glob(ext):
                    try:
                        stat = img_file.stat()
                        created_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
                        sid = f"sc_{game.id}_{img_file.stem}"
                        screenshots.append(
                            Screenshot(
                                id=sid,
                                game_id=game.id,
                                file_path=img_file,
                                created_at=created_at,
                                size_bytes=stat.st_size,
                            )
                        )
                    except OSError:
                        pass

        screenshots.sort(key=lambda s: s.created_at, reverse=True)
        return screenshots
