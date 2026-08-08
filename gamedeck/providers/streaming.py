"""Moonlight and Sunshine streaming target provider plugin for GameDeck."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from gamedeck.models import Game
from gamedeck.plugins import BaseProviderPlugin

__all__ = ["StreamingProvider"]

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class StreamingProvider(BaseProviderPlugin):
    """Discovers remote streaming game targets via Moonlight and Sunshine."""

    name: str = "streaming"
    display_name: str = "Moonlight / Sunshine Remote Stream"

    def is_available(self) -> bool:
        """Check if Moonlight or Sunshine config directory exists."""
        home = Path.home()
        paths = [
            home / ".config" / "Moonlight Game Streaming Project",
            home / ".config" / "sunshine",
        ]
        return any(p.exists() for p in paths)

    def scan(self) -> list[Game]:
        """Scan and return remote stream game targets."""
        games: list[Game] = []
        home = Path.home()

        # Sunshine apps config
        sunshine_apps = home / ".config" / "sunshine" / "apps.json"
        if sunshine_apps.is_file():
            try:
                import json
                with sunshine_apps.open("r", encoding="utf-8") as f:
                    data = json.load(f)

                apps = data.get("apps", []) if isinstance(data, dict) else []
                for app in apps:
                    title = app.get("name", "")
                    if title:
                        gid = f"sunshine_{title.lower().replace(' ', '_')}"
                        games.append(
                            Game(
                                id=gid,
                                name=f"[Stream] {title}",
                                source="sunshine",
                                launcher="moonlight",
                                installed=True,
                            )
                        )
            except Exception as err:
                logger.debug("StreamingProvider failed reading Sunshine apps: %s", err)

        return games
