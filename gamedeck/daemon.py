"""Daemon background service (gamedeckd) maintaining the SQLite cache and watching provider changes."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time
from dataclasses import dataclass, field
from typing import Any

from gamedeck.config import Settings
from gamedeck.metadata_manager import MetadataManager
from gamedeck.provider_manager import ProviderManager
from gamedeck.providers.filesystem import FilesystemProvider
from gamedeck.scanner import Scanner
from gamedeck.search import SearchIndex
from gamedeck.steamgriddb import SteamGridDBClient
from gamedeck.watcher import WatcherManager

__all__ = ["GameDeckDaemon", "main"]

logger = logging.getLogger("gamedeckd")


@dataclass(slots=True)
class GameDeckDaemon:
    """Daemon service that runs in the user session.

    Responsibilities:
    - Maintains the SQLite library and metadata cache.
    - Continuously listens for filesystem changes across all providers.
    - Incremental background scanning when manifests/configs change.
    - Pre-builds and warms the search index so the interactive launcher starts in <100ms.
    - Allows the Rofi UI to read directly from SQLite without scanning providers.

    Attributes:
        settings: Application settings.
        metadata_manager: Metadata and artwork manager.
        scanner: Scanner instance for provider scans.
        watcher: Filesystem watcher listening for provider directory events.
        search_index: In-memory warmed search index.
    """

    settings: Settings = field(default_factory=Settings.load)
    metadata_manager: MetadataManager = field(default_factory=MetadataManager)
    scanner: Scanner | None = None
    watcher: WatcherManager | None = None
    search_index: SearchIndex = field(default_factory=SearchIndex)
    sgdb_client: SteamGridDBClient = field(default_factory=SteamGridDBClient)
    _running: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        """Initialize provider manager, scanner, and watcher."""
        enabled = self.settings.providers.enabled_list()
        recent_limit = self.settings.ui.recent_games_limit

        provider_manager = ProviderManager(
            enabled_providers=enabled,
            recent_limit=recent_limit,
            metadata_cache=self.metadata_manager.metadata_cache,
        )

        if "filesystem" in enabled:
            resolved_paths = self.settings.filesystem.resolved_paths()
            fs_provider = FilesystemProvider(search_dirs=resolved_paths)
            provider_manager.custom_providers["filesystem"] = fs_provider

        self.scanner = Scanner(
            provider_manager=provider_manager,
            metadata_manager=self.metadata_manager,
        )

        self.watcher = WatcherManager(
            scanner=self.scanner,
            on_change_callbacks=[self._on_library_change],
        )

    def start(self) -> None:
        """Start the daemon: perform initial scan, warm cache and search index, and start watcher."""
        self._running = True
        logger.info("Starting gamedeckd v0.5.0 daemon service...")

        # 1. Perform initial scan and warm the SQLite cache & search index
        self.sync_and_warm()

        # 2. Start filesystem watcher for background updates
        if self.watcher is not None:
            self.watcher.start()
            logger.info("gamedeckd filesystem watcher active across all provider roots")

    def stop(self) -> None:
        """Stop the daemon and watcher gracefully."""
        self._running = False
        if self.watcher is not None:
            self.watcher.stop()
        logger.info("gamedeckd daemon stopped gracefully")

    def run_forever(self) -> None:
        """Run the daemon blocking main thread, handling SIGINT and SIGTERM."""
        self.start()

        def _signal_handler(signum: int, frame: Any) -> None:
            logger.info("Received signal %d; shutting down gamedeckd...", signum)
            self.stop()
            sys.exit(0)

        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)

        logger.info("gamedeckd is running in the background. Press Ctrl+C or send SIGTERM to exit.")
        while self._running:
            try:
                time.sleep(1.0)
            except (KeyboardInterrupt, SystemExit):
                break
        self.stop()

    def sync_and_warm(self) -> list[Any]:
        """Perform scan, store to SQLite, build in-memory SearchIndex, and trigger background artwork downloads."""
        if self.scanner is None:
            return []

        t0 = time.perf_counter()
        games = self.scanner.scan()
        self.search_index = SearchIndex.build(games)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        logger.info(
            "gamedeckd refreshed %d games in %.1fms (SearchIndex warmed: %d entries)",
            len(games),
            elapsed_ms,
            len(self.search_index),
        )

        # Trigger background SteamGridDB artwork downloads for games missing artwork
        if self.sgdb_client.is_available():
            missing_artwork = [
                g for g in games
                if g.cover is None or g.hero is None or g.icon is None
            ]
            for game in missing_artwork[:20]:  # Rate-limit: max 20 per sync cycle
                self.sgdb_client.fetch_game_artwork_background(game)
            if missing_artwork:
                logger.debug(
                    "gamedeckd: queued background artwork downloads for %d games via SteamGridDB",
                    min(len(missing_artwork), 20),
                )
        return games

    def _on_library_change(self, events: list[Any]) -> None:
        """Callback triggered when the watcher detects provider modifications."""
        logger.info("gamedeckd detected %d filesystem change(s) — updating SQLite and SearchIndex", len(events))
        self.sync_and_warm()


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for the gamedeckd daemon."""
    parser = argparse.ArgumentParser(
        prog="gamedeckd",
        description="GameDeck Background Daemon & User Service.",
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Perform an immediate library sync, update SQLite cache & search index, and exit",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose debug logging",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] (gamedeckd) %(message)s",
    )

    daemon = GameDeckDaemon()

    if args.sync:
        games = daemon.sync_and_warm()
        print(f"gamedeckd: Synchronized and cached {len(games)} games in SQLite database.")
        return 0

    daemon.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
