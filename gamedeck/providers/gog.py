"""GOG library provider plugin for GameDeck."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from gamedeck.models import Game
from gamedeck.plugins import BaseProviderPlugin

__all__ = ["GOGProvider"]

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class GOGProvider(BaseProviderPlugin):
    """Discovers installed GOG games via Heroic GOG manifests or standalone GOG directory."""

    name: str = "gog"
    display_name: str = "GOG"

    def is_available(self) -> bool:
        """Check if Heroic GOG library or GOG directory exists."""
        home = Path.home()
        gog_paths = [
            home / ".config" / "heroic" / "gog_store",
            home / "GOG Games",
        ]
        return any(p.exists() for p in gog_paths)

    def scan(self) -> list[Game]:
        """Scan and return discovered GOG games."""
        games: list[Game] = []
        home = Path.home()

        # 1. Heroic GOG library
        heroic_gog_dir = home / ".config" / "heroic" / "gog_store"
        installed_file = heroic_gog_dir / "installed.json"

        if installed_file.is_file():
            try:
                with installed_file.open("r", encoding="utf-8") as f:
                    data = json.load(f)

                installed_list = data.get("installed", []) if isinstance(data, dict) else []
                for item in installed_list:
                    title = item.get("title", "")
                    app_name = item.get("appName", "")
                    install_path = item.get("install_path", "")
                    exec_path = item.get("executable", "")

                    if title and app_name:
                        game_id = f"gog_{app_name.lower().replace(' ', '_')}"
                        games.append(
                            Game(
                                id=game_id,
                                name=title,
                                source="gog",
                                launcher="wine" if item.get("platform") == "windows" else "native",
                                executable=Path(exec_path) if exec_path else (Path(install_path) if install_path else None),
                                installed=True,
                                appid=app_name,
                            )
                        )
            except Exception as err:
                logger.debug("GOGProvider failed reading Heroic GOG manifests: %s", err)

        # 2. Standalone ~/GOG Games/ directory
        gog_games_dir = home / "GOG Games"
        if gog_games_dir.is_dir():
            for child in gog_games_dir.iterdir():
                if child.is_dir():
                    title = child.name.replace("_", " ").strip()
                    game_id = f"gog_{child.name.lower()}"
                    # Avoid duplicate if already found via Heroic
                    if not any(g.id == game_id for g in games):
                        games.append(
                            Game(
                                id=game_id,
                                name=title,
                                source="gog",
                                launcher="native",
                                executable=child,
                                installed=True,
                            )
                        )

        return games
