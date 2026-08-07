"""Main GameDeck application orchestrating scanner, UI, and launcher backends."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gamedeck.launchers import launch
from gamedeck.models import Game
from gamedeck.scanner import Scanner
from gamedeck.ui.rofi import RofiUI

__all__ = ["GameDeck", "main"]


@dataclass(slots=True)
class GameDeck:
    """Core GameDeck application coordinating scanning, interactive menu, and game launching.

    Attributes:
        scanner: Scanner instance used for discovering games across providers.
        ui: RofiUI frontend used for presenting the searchable menu to the user.
        version: Application release version string.
    """

    scanner: Scanner = field(default_factory=Scanner)
    ui: RofiUI = field(default_factory=RofiUI)
    version: str = "0.1.0"

    def run(self) -> int:
        """Execute the GameDeck workflow.

        Scans for games across all configured providers, displays the searchable
        Rofi UI, and executes the selected game via its appropriate launcher backend.

        Returns:
            Exit status code (0 for success, non-zero on error).
        """
        # Step 1: Scan for all games via ProviderManager/Scanner
        games = self.scanner.scan()

        if not games:
            print("GameDeck: No installed games detected across configured providers.")
            return 0

        # Step 2: Present games to user in Rofi UI
        try:
            selected_game = self.ui.select(games)
        except RuntimeError as err:
            print(f"GameDeck UI Error: {err}", file=sys.stderr)
            return 1

        # Step 3: Launch selected game if user did not cancel/dismiss
        if selected_game is not None:
            try:
                launch(selected_game)
            except Exception as err:
                print(f"GameDeck Launch Error: Failed to launch '{selected_game.name}': {err}", file=sys.stderr)
                return 1

        return 0


def main() -> None:
    """Application main entry point."""
    app = GameDeck()
    sys.exit(app.run())
