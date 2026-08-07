"""Main GameDeck application orchestrating scanner, UI, and launcher backends."""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gamedeck.config import Settings
from gamedeck.database import MetadataCache
from gamedeck.launchers import launch
from gamedeck.models import Game
from gamedeck.provider_manager import ProviderManager, sort_games_with_recents
from gamedeck.providers.filesystem import FilesystemProvider
from gamedeck.scanner import Scanner
from gamedeck.ui.rofi import RofiUI

__all__ = ["GameDeck", "main"]

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class GameDeck:
    """Core GameDeck application coordinating scanning, interactive menu, and game launching.

    Attributes:
        settings: Application settings loaded from TOML or defaults.
        scanner: Scanner instance used for discovering games across providers.
        ui: RofiUI frontend used for presenting the searchable menu to the user.
        metadata_cache: MetadataCache for SQLite persistence and launch tracking.
        version: Application release version string.
    """

    settings: Settings = field(default_factory=Settings.load)
    scanner: Scanner | None = None
    ui: RofiUI | None = None
    metadata_cache: MetadataCache = field(default_factory=MetadataCache)
    version: str = "0.1.0"

    def __post_init__(self) -> None:
        """Initialize scanner and UI with settings if not explicitly provided."""
        if self.scanner is None:
            # Configure provider manager with enabled providers from settings
            enabled = self.settings.providers.enabled_list()
            recent_limit = self.settings.ui.recent_games_limit
            provider_manager = ProviderManager(
                enabled_providers=enabled,
                recent_limit=recent_limit,
            )

            # Wire configured filesystem search paths if filesystem provider is active
            if "filesystem" in enabled:
                resolved_paths = self.settings.filesystem.resolved_paths()
                fs_provider = FilesystemProvider(search_dirs=resolved_paths)
                provider_manager.custom_providers["filesystem"] = fs_provider

            self.scanner = Scanner(
                provider_manager=provider_manager,
                metadata_cache=self.metadata_cache,
            )

        if self.ui is None:
            theme = self.settings.ui.rofi_theme if self.settings.ui.rofi_theme else None
            self.ui = RofiUI(theme=theme)

    def run(self, argv: list[str] | None = None) -> int:
        """Execute the GameDeck workflow.

        Scans for games across all configured providers, displays the searchable
        Rofi UI with favorites and recently played games prioritized, provides interactive
        game cards for launching and toggling favorites, and executes games cleanly.

        Args:
            argv: Optional list of command-line arguments.

        Returns:
            Exit status code (0 for success, non-zero on error).
        """
        parser = argparse.ArgumentParser(
            prog="GameDeck",
            description="Universal Game Launcher for Linux with Rofi frontend.",
        )
        parser.add_argument(
            "--toggle-fav",
            "--fav",
            metavar="GAME",
            help="Toggle favorite status for a game by ID or partial name",
        )
        parser.add_argument(
            "--list",
            action="store_true",
            help="List all discovered games in the terminal with favorites and play stats",
        )

        args, _ = parser.parse_known_args(argv)

        if self.scanner is None:
            return 1

        games = self.scanner.scan()

        if not games:
            logger.info("No games discovered across enabled providers.")
            print("GameDeck: No installed games detected across configured providers.")
            return 0

        # Handle CLI --toggle-fav
        if args.toggle_fav:
            target = args.toggle_fav.lower().strip()
            matched = [g for g in games if target in g.id.lower() or target in g.name.lower()]
            if not matched:
                print(f"GameDeck: No game found matching '{args.toggle_fav}'.")
                return 1
            game = matched[0]
            new_fav = self.metadata_cache.toggle_favorite(game.id)
            star = "★ " if new_fav else ""
            print(f"GameDeck: Favorite toggled for {star}'{game.name}' -> {new_fav}")
            return 0

        # Handle CLI --list
        if args.list:
            print(f"{'FAV':<4} {'GAME TITLE':<32} {'SOURCE':<10} {'LAUNCHES':<10} {'LAST PLAYED'}")
            print("-" * 80)
            for g in games:
                star = " ★ " if g.favorite else "   "
                recent = g.last_played[:19] if g.last_played else "Never"
                print(f"{star:<4} {g.name:<32} {g.source:<10} {g.launch_count:<10} {recent}")
            return 0

        # Interactive Rofi menu loop
        if self.ui is None:
            return 1

        recent_limit = self.settings.ui.recent_games_limit

        while True:
            try:
                selected_game, action = self.ui.select_with_action(games)
            except RuntimeError as err:
                logger.error("UI error during game selection: %s", err)
                print(f"GameDeck UI Error: {err}", file=sys.stderr)
                return 1

            if selected_game is None or action == "cancel":
                return 0

            if action == "back":
                continue

            if action == "toggle_favorite":
                # Toggle favorite state in SQLite and update game object in-memory
                new_state = self.metadata_cache.toggle_favorite(selected_game.id)
                selected_game.favorite = new_state
                # Re-sort games with favorites and recents at the top instantly
                games = sort_games_with_recents(games, recent_limit=recent_limit)
                logger.info("Toggled favorite for '%s' -> %s", selected_game.name, new_state)
                continue

            # Launch selected game and record launch statistics
            logger.info("Launching selected game: %s [%s]", selected_game.name, selected_game.id)
            try:
                launch(selected_game)
                self.metadata_cache.record_launch(selected_game.id)
            except Exception as err:
                logger.error("Failed to launch '%s': %s", selected_game.name, err)
                print(f"GameDeck Launch Error: Failed to launch '{selected_game.name}': {err}", file=sys.stderr)
                return 1

            return 0


def main() -> None:
    """Application main entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    app = GameDeck()
    sys.exit(app.run(sys.argv[1:]))
