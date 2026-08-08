"""itch.io library provider plugin for GameDeck."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from gamedeck.models import Game
from gamedeck.plugins import BaseProviderPlugin

__all__ = ["ItchProvider"]

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ItchProvider(BaseProviderPlugin):
    """Discovers games installed via the itch.io desktop app."""

    name: str = "itch"
    display_name: str = "itch.io"

    def is_available(self) -> bool:
        """Check if itch.io data directory exists."""
        home = Path.home()
        itch_db = home / ".config" / "itch" / "db" / "butler.db"
        return itch_db.is_file()

    def scan(self) -> list[Game]:
        """Scan butler.db for installed itch.io games."""
        games: list[Game] = []
        home = Path.home()
        itch_db = home / ".config" / "itch" / "db" / "butler.db"

        if not itch_db.is_file():
            return games

        try:
            conn = sqlite3.connect(f"file:{itch_db}?mode=ro", uri=True)
            cursor = conn.cursor()
            cursor.execute("SELECT id, title, target_exec, install_folder FROM caves")
            rows = cursor.fetchall()

            for row in rows:
                cave_id, title, exec_path, folder = row[0], row[1], row[2], row[3]
                if title:
                    game_id = f"itch_{cave_id}"
                    executable = Path(exec_path) if exec_path else (Path(folder) if folder else None)
                    games.append(
                        Game(
                            id=game_id,
                            name=title,
                            source="itch",
                            launcher="native",
                            executable=executable,
                            installed=True,
                        )
                    )
            conn.close()
        except Exception as err:
            logger.debug("ItchProvider failed reading butler.db: %s", err)

        return games
