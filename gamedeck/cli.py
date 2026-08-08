"""Subcommand Command Line Interface for GameDeck."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from gamedeck.app import GameDeck
from gamedeck.backup import BackupManager
from gamedeck.search import SearchIndex
from gamedeck.stats import LibraryStatsProvider

__all__ = ["main_cli"]


def main_cli(argv: list[str] | None = None) -> int:
    """Execute GameDeck CLI subcommands."""
    parser = argparse.ArgumentParser(
        prog="gamedeck",
        description="GameDeck Linux Gaming Platform CLI",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # gamedeck list
    list_parser = subparsers.add_parser("list", help="List all discovered games")
    list_parser.add_argument("--json", action="store_true", help="Output as JSON")

    # gamedeck launch <game>
    launch_parser = subparsers.add_parser("launch", help="Launch a game by ID or title")
    launch_parser.add_argument("target", help="Game ID or partial title to launch")

    # gamedeck search <query>
    search_parser = subparsers.add_parser("search", help="Search games using advanced multi-token query")
    search_parser.add_argument("query", help="Search query (e.g. 'Wukong', 'launcher:wine', 'favorite:true')")

    # gamedeck sync
    sync_parser = subparsers.add_parser("sync", help="Trigger full provider sync and SQLite cache update")

    # gamedeck artwork
    artwork_parser = subparsers.add_parser("artwork", help="Trigger background SteamGridDB artwork fetch")
    artwork_parser.add_argument("--game", help="Target game ID or title")

    # gamedeck backup
    backup_parser = subparsers.add_parser("backup", help="Export GameDeck database backup JSON")
    backup_parser.add_argument("--out", default="gamedeck_backup.json", help="Output JSON path")

    args = parser.parse_args(argv)

    app = GameDeck()
    cached_games = app.metadata_manager.metadata_cache.get_all_cached_games()
    games = cached_games if cached_games else app.scanner.scan()

    if args.command == "list":
        print(f"{'FAV':<4} {'GAME TITLE':<32} {'SOURCE':<10} {'LAUNCHES':<10} {'LAST PLAYED'}")
        print("-" * 80)
        for g in games:
            star = " ★ " if g.favorite else "   "
            recent = g.last_played[:19] if g.last_played else "Never"
            print(f"{star:<4} {g.name:<32} {g.source:<10} {g.launch_count:<10} {recent}")
        return 0

    if args.command == "search":
        search_index = SearchIndex.build(games)
        results = search_index.search(args.query)
        print(f"Search results for '{args.query}' ({len(results)} matches):")
        print("-" * 80)
        for res in results:
            g = res.game
            star = "★ " if g.favorite else ""
            print(f"  {star}{g.name:<32} [{g.id}] ({g.source}) - score: {res.score:.2f}")
        return 0

    if args.command == "launch":
        search_index = SearchIndex.build(games)
        results = search_index.search(args.target)
        if not results:
            print(f"GameDeck CLI: No game matching '{args.target}' found.")
            return 1
        target_game = results[0].game
        print(f"Launching {target_game.name} [{target_game.id}]...")
        from gamedeck.launchers import launch
        launch(target_game)
        app.metadata_manager.record_launch(target_game.id)
        return 0

    if args.command == "sync":
        scanned = app.scanner.scan()
        print(f"GameDeck CLI: Sync complete across enabled providers ({len(scanned)} games updated).")
        return 0

    if args.command == "artwork":
        if app.metadata_manager.steamgriddb and app.metadata_manager.steamgriddb.is_available():
            for g in games[:10]:
                app.metadata_manager.steamgriddb.fetch_game_artwork_background(g)
            print(f"GameDeck CLI: Queued artwork downloads via SteamGridDB.")
        else:
            print("GameDeck CLI: SteamGridDB key not set. Set STEAMGRIDDB_API_KEY env var or in config.toml.")
        return 0

    if args.command == "backup":
        out_p = Path(args.out)
        mgr = BackupManager(metadata_cache=app.metadata_manager.metadata_cache)
        data = mgr.export_backup(out_p)
        print(f"GameDeck CLI: Backup exported successfully to '{out_p.resolve()}'.")
        return 0

    # Default fallback to app.run if no subcommand match
    return app.run(argv)
