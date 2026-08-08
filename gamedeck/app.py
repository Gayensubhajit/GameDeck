"""Main GameDeck application orchestrating scanner, UI, and launcher backends."""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gamedeck.backup import BackupManager
from gamedeck.collections import CollectionManager, GameCollection
from gamedeck.config import Settings
from gamedeck.database import MetadataCache
from gamedeck.details import GameDetails, GameDetailsProvider
from gamedeck.importer import LibraryImporter
from gamedeck.launchers import launch
from gamedeck.metadata_manager import MetadataManager
from gamedeck.models import Game
from gamedeck.provider_manager import ProviderManager, sort_games_with_recents
from gamedeck.providers.filesystem import FilesystemProvider
from gamedeck.scanner import Scanner
from gamedeck.search import SearchIndex
from gamedeck.ui.rofi import RofiUI
from gamedeck.watcher import WatcherManager

__all__ = ["GameDeck", "main"]

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class GameDeck:
    """Core GameDeck application coordinating scanning, interactive menu, and game launching.

    Attributes:
        settings: Application settings loaded from TOML or defaults.
        scanner: Scanner instance used for discovering games across providers.
        ui: RofiUI frontend used for presenting the searchable menu to the user.
        metadata_manager: MetadataManager for SQLite persistence, launch tracking, and artwork.
        version: Application release version string.
    """

    settings: Settings = field(default_factory=Settings.load)
    scanner: Scanner | None = None
    ui: RofiUI | None = None
    metadata_manager: MetadataManager = field(default_factory=MetadataManager)
    watcher: WatcherManager | None = None
    version: str = "0.5.0"

    @property
    def metadata_cache(self) -> MetadataCache:
        """Backwards-compatibility property for metadata_cache."""
        return self.metadata_manager.metadata_cache

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
                metadata_manager=self.metadata_manager,
            )

        if self.watcher is None:
            self.watcher = WatcherManager(scanner=self.scanner)

        # Propagate offline_mode settings to artwork pipeline
        if hasattr(self.settings, "ui") and hasattr(self.settings.ui, "offline_mode"):
            self.metadata_manager.artwork_cache.offline_mode = self.settings.ui.offline_mode
            if self.metadata_manager.steamgriddb:
                self.metadata_manager.steamgriddb.offline_mode = self.settings.ui.offline_mode

        if self.ui is None:
            theme = self.settings.ui.rofi_theme if self.settings.ui.rofi_theme else None
            self.ui = RofiUI(
                theme=theme,
                quick_launch=self.settings.ui.quick_launch,
                secondary_action_key=self.settings.ui.secondary_action_key,
                default_view=self.settings.ui.default_view,
                grid_columns=self.settings.ui.grid_columns,
                grid_card_style=self.settings.ui.grid_card_style,
                db_cache=self.metadata_manager.metadata_cache,
            )

    def sort_library_games(self, games: list[Game]) -> list[Game]:
        """Sort library games according to UX rules:
        1. Favorites are always pinned at the top (sorted by name).
        2. Recently Played appears directly below Favorites (sorted by last_played desc).
        3. Remaining games sorted alphabetically by name.
        """
        show_recent = self.settings.ui.show_recently_played
        recent_limit = self.settings.ui.recent_games_limit

        favorites = [g for g in games if g.favorite]
        favorites.sort(key=lambda g: (g.name or "").lower())

        fav_ids = {g.id for g in favorites}
        non_favs = [g for g in games if g.id not in fav_ids]

        if show_recent:
            recently_played = [g for g in non_favs if g.last_played]
            recently_played.sort(key=lambda g: g.last_played or "", reverse=True)
            recent_subset = recently_played[:recent_limit]
            recent_ids = {g.id for g in recent_subset}

            remaining = [g for g in non_favs if g.id not in recent_ids]
            remaining.sort(key=lambda g: (g.name or "").lower())

            return favorites + recent_subset + remaining
        else:
            non_favs.sort(key=lambda g: (g.name or "").lower())
            return favorites + non_favs

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
        parser.add_argument(
            "-i",
            "--details",
            "--info",
            metavar="GAME",
            help="Display comprehensive metadata details for a game by ID or partial title without provider scanning",
        )
        parser.add_argument(
            "--collections",
            action="store_true",
            help="List all dynamic and custom collections and their game counts",
        )
        parser.add_argument(
            "-c",
            "--collection",
            metavar="NAME",
            help="Filter and view games within a specific collection (e.g. 'favorites', 'steam', 'recent', 'lutris')",
        )
        parser.add_argument(
            "--import-categories",
            action="store_true",
            help="Detect and import categories from Steam, Lutris, and Heroic into GameDeck Collections without duplicates",
        )
        parser.add_argument(
            "--backup",
            "--export",
            metavar="FILE",
            nargs="?",
            const="gamedeck_backup.json",
            help="Export complete GameDeck state (favorites, collections, tags, overrides, history, artwork) to JSON",
        )
        parser.add_argument(
            "--restore",
            metavar="FILE",
            help="Restore GameDeck database and customizations from a backup JSON file",
        )

        parser.add_argument(
            "--rescan",
            action="store_true",
            help="Force a full rescan of all game providers, bypassing the incremental SQLite cache",
        )
        parser.add_argument(
            "--stats",
            action="store_true",
            help="Print library statistics (total games, playtime, most played, launcher distribution)",
        )
        parser.add_argument(
            "--view",
            choices=["list", "grid", "compact", "hero", "carousel"],
            help="Select presentation view mode ('list', 'grid', 'compact', 'hero', 'carousel')",
        )
        parser.add_argument(
            "--grid",
            action="store_true",
            help="Launch directly in Grid View mode",
        )

        args, _ = parser.parse_known_args(argv)

        if getattr(args, "grid", False):
            if self.ui is not None:
                self.ui.switch_to_grid()
        elif getattr(args, "view", None):
            if self.ui is not None:
                self.ui.switch_to_view(args.view)

        if self.scanner is None:
            return 1

        # Fast direct SQLite cache load (<10ms) without scanning providers directly
        # Skip cache if user requested a forced rescan
        force_rescan = getattr(args, "rescan", False)
        cached_games = [] if force_rescan else self.metadata_manager.metadata_cache.get_all_cached_games()
        if cached_games:
            # Apply provider-priority deduplication — cached_games contains raw per-provider rows,
            # so Lutris must win over Filesystem for the same title (e.g. Black Myth: Wukong).
            games = self.scanner.provider_manager.merge_and_deduplicate(cached_games)
            logger.debug("Instant launcher startup: loaded %d games directly from SQLite cache (deduplicated from %d rows)", len(games), len(cached_games))
        else:
            # Cold start fallback or forced rescan
            games = self.scanner.scan()
            if force_rescan:
                logger.info("Forced rescan complete: %d games discovered", len(games))

        if not games:
            logger.info("No games discovered across enabled providers.")
            print("GameDeck: No installed games detected across configured providers.")
            return 0

        # Handle CLI --toggle-fav
        if args.toggle_fav:
            target = args.toggle_fav.strip()
            search_index = SearchIndex.build(games)
            results = search_index.search(target)
            if not results:
                # Fallback to direct ID match
                matched_games = [g for g in games if target.lower() in g.id.lower()]
                if not matched_games:
                    print(f"GameDeck: No game found matching '{args.toggle_fav}'.")
                    return 1
                game = matched_games[0]
            else:
                game = results[0].game

            new_fav = self.metadata_manager.toggle_favorite(game.id)
            star = "★ " if new_fav else ""
            print(f"GameDeck: Favorite toggled for {star}'{game.name}' -> {new_fav}")
            return 0

        # Handle CLI --details / --info
        if args.details:
            target = args.details.strip()
            details_provider = GameDetailsProvider(metadata_cache=self.metadata_manager.metadata_cache)
            search_index = SearchIndex.build(games)
            results = search_index.search(target)
            if results:
                details = details_provider.get_details(results[0].game)
            else:
                # Direct ID match
                details = details_provider.get_details(target)

            if details is None:
                print(f"GameDeck: No details found for game '{args.details}'.")
                return 1

            print("=" * 48)
            print(f"  GAME DETAILS: {details.title}")
            print("=" * 48)
            print(details.formatted_summary())
            print("=" * 48)
            return 0

        # Handle CLI --import-categories
        if args.import_categories:
            importer = LibraryImporter(metadata_cache=self.metadata_manager.metadata_cache)
            results = importer.import_all(games)
            print("=" * 60)
            print("  LIBRARY CATEGORY IMPORT SUMMARY")
            print("=" * 60)
            for res in results:
                print(f"  [{res.launcher.upper():<8}] Collections Created: {res.collections_created:<4} | Items Imported: {res.items_imported:<4}")
            print("=" * 60)
            return 0
        if args.collections:
            manager = CollectionManager(metadata_cache=self.metadata_manager.metadata_cache)
            colls = manager.get_all_collections(games)
            print(f"{'ICON':<5} {'COLLECTION':<25} {'COUNT':<8} {'TYPE':<10} {'DESCRIPTION'}")
            print("-" * 80)
            for c in colls:
                ctype = "Dynamic" if c.is_dynamic else "Custom"
                print(f"{c.icon:<5} {c.name:<25} {c.count():<8} {ctype:<10} {c.description}")
            return 0

        # Handle CLI --backup
        if args.backup:
            out_path = Path(args.backup)
            mgr = BackupManager(metadata_cache=self.metadata_manager.metadata_cache)
            data = mgr.export_backup(out_path)
            print(f"GameDeck: Backup exported successfully to '{out_path.resolve()}' ({len(data.favorites)} favorites, {len(data.collections)} collections, {len(data.tags)} tags).")
            return 0

        # Handle CLI --restore
        if args.restore:
            in_path = Path(args.restore)
            if not in_path.is_file():
                print(f"GameDeck Error: Backup file '{in_path}' not found.", file=sys.stderr)
                return 1
            mgr = BackupManager(metadata_cache=self.metadata_manager.metadata_cache)
            mgr.restore_backup(in_path)
            print(f"GameDeck: Backup restored successfully from '{in_path.resolve()}'.")
            return 0

        # Handle CLI --collection <NAME>
        if args.collection:
            target_coll = args.collection.strip().lower()
            manager = CollectionManager(metadata_cache=self.metadata_manager.metadata_cache)
            colls = manager.get_all_collections(games)
            matched = [c for c in colls if target_coll in c.name.lower() or target_coll in c.id.lower()]
            if not matched:
                print(f"GameDeck: No collection found matching '{args.collection}'.")
                return 1
            chosen = matched[0]
            print(f"=== {chosen.icon}  {chosen.name} ({chosen.count()} games) ===")
            for g in chosen.games:
                star = " ★ " if g.favorite else "   "
                print(f"{star:<4} {g.name:<32} {g.source:<10}")
            return 0

        # Handle CLI --stats
        if args.stats:
            from gamedeck.stats import LibraryStatsProvider
            stats_provider = LibraryStatsProvider(metadata_cache=self.metadata_manager.metadata_cache)
            stats = stats_provider.calculate_stats(games)
            print(stats.formatted_summary())
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
        coll_manager = CollectionManager(metadata_cache=self.metadata_manager.metadata_cache)

        while True:
            all_colls = coll_manager.get_all_collections(games)
            dynamic_colls = [c for c in all_colls if c.is_dynamic and c.count() > 0]
            custom_colls = [c for c in all_colls if not c.is_dynamic and c.count() > 0]

            # Filter hidden games from the interactive library view
            visible_games = [g for g in games if not getattr(g, "hidden", False)]
            sorted_games = self.sort_library_games(visible_games)

            try:
                selected_game, action_result = self.ui.select_with_action(
                    sorted_games,
                    dynamic_collections=dynamic_colls,
                    custom_collections=custom_colls,
                )
            except RuntimeError as err:
                logger.error("UI error during game selection: %s", err)
                print(f"GameDeck UI Error: {err}", file=sys.stderr)
                return 1

            if selected_game is None:
                return 0

            # Submenu 1: Collections Submenu
            if selected_game == "NAV_COLLECTIONS":
                chosen_coll = self.ui.select_collection(all_colls, prompt="GameDeck > Collections")
                if chosen_coll == "NAV_CREATE_COLLECTION":
                    new_name = self.ui.prompt_text("New Collection Name:")
                    if new_name and new_name.strip():
                        coll_manager.create_custom_collection(new_name.strip())
                    continue
                elif isinstance(chosen_coll, GameCollection):
                    if chosen_coll.games:
                        sub_game, sub_act = self.ui.select_with_action(
                            chosen_coll.games,
                            prompt=f"GameDeck > Collections > {chosen_coll.name}",
                        )
                        if sub_game and isinstance(sub_game, Game):
                            selected_game, action_result = sub_game, sub_act
                        else:
                            continue
                    else:
                        continue
                else:
                    continue

            # Submenu 2: Tags Submenu
            if selected_game == "NAV_TAGS":
                from gamedeck.tags import TagManager

                tag_manager = TagManager(metadata_cache=self.metadata_manager.metadata_cache)
                all_tags = tag_manager.get_all_tags()
                chosen_tag = self.ui.select_tag(all_tags, prompt="GameDeck > Filter by Tag")
                if chosen_tag:
                    tagged_games = tag_manager.get_games_for_tag(chosen_tag.name, games)
                    if tagged_games:
                        sub_game, sub_act = self.ui.select_with_action(
                            tagged_games,
                            prompt=f"GameDeck > Tags > {chosen_tag.name}",
                        )
                        if sub_game and isinstance(sub_game, Game):
                            selected_game, action_result = sub_game, sub_act
                        else:
                            continue
                    else:
                        continue
                else:
                    continue

            # Submenu 3: Library Stats
            if selected_game == "NAV_STATS":
                from gamedeck.stats import LibraryStatsProvider

                stats_provider = LibraryStatsProvider(metadata_cache=self.metadata_manager.metadata_cache)
                stats = stats_provider.calculate_stats(games)
                if self.ui is not None:
                    self.ui.show_game_details_dialog(stats.formatted_summary(), "GameDeck", prompt="📊 Library Stats")
                continue

            # Legacy inline collection handling fallback
            if isinstance(selected_game, GameCollection):
                if not selected_game.games:
                    continue
                sub_game, sub_act = self.ui.select_with_action(
                    selected_game.games,
                    prompt=f"GameDeck > Collections > {selected_game.name}",
                )
                if sub_game and isinstance(sub_game, Game):
                    selected_game, action_result = sub_game, sub_act
                else:
                    continue

            if not isinstance(selected_game, Game):
                continue

            # Unpack action name and payload
            action_name = action_result[0] if isinstance(action_result, tuple) else action_result
            action_obj = action_result[1] if isinstance(action_result, tuple) else None

            if action_name in ("back", "nav", "cancel"):
                continue

            if action_name == "select_profile":
                from gamedeck.profiles import LaunchProfile, ProfileManager

                prof_manager = ProfileManager(metadata_cache=self.metadata_manager.metadata_cache)
                while True:
                    profiles = prof_manager.get_profiles(selected_game)
                    act, chosen_prof = self.ui.show_select_profile_dialog(profiles, selected_game.name)
                    if act in ("cancel", "done") or chosen_prof is None and act != "prompt_new_profile":
                        break
                    elif act == "configure_profile" and chosen_prof:
                        curr_prof = chosen_prof
                        while True:
                            sub_act, _ = self.ui.show_configure_profile_dialog(curr_prof, selected_game.name)
                            if sub_act in ("cancel", "done"):
                                break
                            elif sub_act == "set_default":
                                prof_manager.set_default_profile(selected_game.id, curr_prof.id)
                                selected_game.launcher = curr_prof.launcher
                                if curr_prof.executable:
                                    selected_game.executable = curr_prof.executable
                                logger.info("Set default profile to '%s' for '%s'", curr_prof.name, selected_game.name)
                                curr_prof = LaunchProfile(
                                    id=curr_prof.id,
                                    game_id=curr_prof.game_id,
                                    name=curr_prof.name,
                                    launcher=curr_prof.launcher,
                                    executable=curr_prof.executable,
                                    launch_args=curr_prof.launch_args,
                                    env_vars=curr_prof.env_vars,
                                    use_gamemode=curr_prof.use_gamemode,
                                    use_gamescope=curr_prof.use_gamescope,
                                    use_mangohud=curr_prof.use_mangohud,
                                    use_obs_vkcapture=curr_prof.use_obs_vkcapture,
                                    pre_launch_script=curr_prof.pre_launch_script,
                                    post_exit_script=curr_prof.post_exit_script,
                                    is_default=True,
                                    created_at=curr_prof.created_at,
                                )
                            elif sub_act in ("toggle_gamemode", "toggle_gamescope", "toggle_mangohud", "toggle_obs"):
                                updated_prof = LaunchProfile(
                                    id=curr_prof.id,
                                    game_id=curr_prof.game_id,
                                    name=curr_prof.name,
                                    launcher=curr_prof.launcher,
                                    executable=curr_prof.executable,
                                    launch_args=curr_prof.launch_args,
                                    env_vars=curr_prof.env_vars,
                                    use_gamemode=not curr_prof.use_gamemode if sub_act == "toggle_gamemode" else curr_prof.use_gamemode,
                                    use_gamescope=not curr_prof.use_gamescope if sub_act == "toggle_gamescope" else curr_prof.use_gamescope,
                                    use_mangohud=not curr_prof.use_mangohud if sub_act == "toggle_mangohud" else curr_prof.use_mangohud,
                                    use_obs_vkcapture=not curr_prof.use_obs_vkcapture if sub_act == "toggle_obs" else curr_prof.use_obs_vkcapture,
                                    pre_launch_script=curr_prof.pre_launch_script,
                                    post_exit_script=curr_prof.post_exit_script,
                                    is_default=curr_prof.is_default,
                                    created_at=curr_prof.created_at,
                                )
                                prof_manager.save_profile(updated_prof)
                                curr_prof = updated_prof
                                logger.info("Toggled wrapper '%s' on profile '%s'", sub_act, curr_prof.name)
                            elif sub_act == "edit_pre_script":
                                pre_s = self.ui.prompt_text("Pre-launch Command or Script Path:")
                                if pre_s is not None:
                                    updated_prof = LaunchProfile(
                                        id=curr_prof.id,
                                        game_id=curr_prof.game_id,
                                        name=curr_prof.name,
                                        launcher=curr_prof.launcher,
                                        executable=curr_prof.executable,
                                        launch_args=curr_prof.launch_args,
                                        env_vars=curr_prof.env_vars,
                                        use_gamemode=curr_prof.use_gamemode,
                                        use_gamescope=curr_prof.use_gamescope,
                                        use_mangohud=curr_prof.use_mangohud,
                                        use_obs_vkcapture=curr_prof.use_obs_vkcapture,
                                        pre_launch_script=pre_s.strip(),
                                        post_exit_script=curr_prof.post_exit_script,
                                        is_default=curr_prof.is_default,
                                        created_at=curr_prof.created_at,
                                    )
                                    prof_manager.save_profile(updated_prof)
                                    curr_prof = updated_prof
                            elif sub_act == "edit_post_script":
                                post_s = self.ui.prompt_text("Post-exit Command or Script Path:")
                                if post_s is not None:
                                    updated_prof = LaunchProfile(
                                        id=curr_prof.id,
                                        game_id=curr_prof.game_id,
                                        name=curr_prof.name,
                                        launcher=curr_prof.launcher,
                                        executable=curr_prof.executable,
                                        launch_args=curr_prof.launch_args,
                                        env_vars=curr_prof.env_vars,
                                        use_gamemode=curr_prof.use_gamemode,
                                        use_gamescope=curr_prof.use_gamescope,
                                        use_mangohud=curr_prof.use_mangohud,
                                        use_obs_vkcapture=curr_prof.use_obs_vkcapture,
                                        pre_launch_script=curr_prof.pre_launch_script,
                                        post_exit_script=post_s.strip(),
                                        is_default=curr_prof.is_default,
                                        created_at=curr_prof.created_at,
                                    )
                                    prof_manager.save_profile(updated_prof)
                                    curr_prof = updated_prof
                    elif act == "prompt_new_profile":
                        new_pname = self.ui.prompt_text("New Profile Name (e.g. MangoHud, Gamescope):")
                        if new_pname and new_pname.strip():
                            new_pid = f"{selected_game.id}_{new_pname.lower().replace(' ', '_')}"
                            new_prof = LaunchProfile(
                                id=new_pid,
                                game_id=selected_game.id,
                                name=new_pname.strip(),
                                launcher="wine",
                                executable=selected_game.executable,
                                is_default=False,
                            )
                            prof_manager.save_profile(new_prof)
                continue

            if action_name == "manage_collections":
                coll_manager = CollectionManager(metadata_cache=self.metadata_manager.metadata_cache)
                while True:
                    customs = coll_manager.get_custom_collections(games)
                    member_cids = {c.id for c in customs if any(g.id == selected_game.id for g in c.games)}
                    act, payload = self.ui.show_manage_collections_dialog(customs, member_cids, selected_game.name)
                    if act in ("cancel", "done") or payload is None and act != "prompt_new_collection":
                        break
                    elif act == "add_to_collection" and payload:
                        coll_manager.add_game_to_collection(payload, selected_game.id)
                    elif act == "remove_from_collection" and payload:
                        coll_manager.remove_game_from_collection(payload, selected_game.id)
                    elif act == "prompt_new_collection":
                        new_name = self.ui.prompt_text("New Collection Name:")
                        if new_name and new_name.strip():
                            new_cid = coll_manager.create_custom_collection(new_name.strip())
                            coll_manager.add_game_to_collection(new_cid, selected_game.id)
                continue

            if action_name == "manage_saves":
                from gamedeck.saves import SaveManager
                save_mgr = SaveManager(metadata_cache=self.metadata_manager.metadata_cache)
                while True:
                    backups = save_mgr.list_backups(selected_game.id)
                    act, payload = self.ui.show_saves_dialog(backups, selected_game.name)
                    if act in ("cancel", "done"):
                        break
                    elif act == "create_backup":
                        discovered = save_mgr.discover_save_paths(selected_game)
                        target_path = discovered[0] if discovered else (selected_game.executable.parent if selected_game.executable else None)
                        if target_path:
                            save_mgr.create_backup(selected_game, target_path)
                            logger.info("Save backup created for '%s'", selected_game.name)
                        break
                    elif act == "restore_backup" and payload:
                        discovered = save_mgr.discover_save_paths(selected_game)
                        target_dir = discovered[0] if discovered else (selected_game.executable.parent if selected_game.executable else Path.home())
                        save_mgr.restore_backup(payload, target_dir)
                        logger.info("Restored save backup for '%s'", selected_game.name)
                        break
                continue

            if action_name == "view_screenshots":
                from gamedeck.screenshots import ScreenshotManager
                sc_mgr = ScreenshotManager()
                screenshots = sc_mgr.discover_screenshots(selected_game)
                self.ui.show_screenshots_dialog(screenshots, selected_game.name)
                continue

            if action_name == "edit_tags":
                from gamedeck.tags import TagManager

                tag_manager = TagManager(metadata_cache=self.metadata_manager.metadata_cache)
                while True:
                    all_tags = tag_manager.get_all_tags()
                    game_tags = tag_manager.get_tags_for_game(selected_game.id)
                    act, payload = self.ui.show_edit_tags_dialog(all_tags, game_tags, selected_game.name)
                    if act in ("cancel", "done") or payload is None and act != "prompt_new_tag":
                        break
                    elif act == "add_tag" and payload:
                        tag_manager.add_tag_to_game(selected_game.id, payload)
                    elif act == "remove_tag" and payload:
                        tag_manager.remove_tag_from_game(selected_game.id, payload)
                    elif act == "prompt_new_tag":
                        new_tag = self.ui.prompt_text("New Tag Label (e.g. Soulslike, Finished):")
                        if new_tag and new_tag.strip():
                            tag_manager.add_tag_to_game(selected_game.id, new_tag.strip())
                continue

            if action_name == "edit_properties":
                while True:
                    field_name, new_val = self.ui.show_edit_properties_dialog(selected_game)
                    if field_name in ("cancel", "done") or not new_val:
                        break
                    if field_name == "edit_title":
                        self.metadata_manager.metadata_cache.update_game_properties(selected_game.id, name=new_val)
                        selected_game.name = new_val
                    elif field_name == "edit_executable":
                        self.metadata_manager.metadata_cache.update_game_properties(selected_game.id, executable=new_val)
                        selected_game.executable = Path(new_val)
                    elif field_name == "edit_launcher":
                        self.metadata_manager.metadata_cache.update_game_properties(selected_game.id, launcher=new_val)
                        selected_game.launcher = new_val
                    elif field_name == "edit_icon":
                        self.metadata_manager.metadata_cache.update_game_properties(selected_game.id, icon=new_val)
                        selected_game.icon = Path(new_val)
                    elif field_name == "edit_cover":
                        self.metadata_manager.metadata_cache.update_game_properties(selected_game.id, cover=new_val)
                        selected_game.cover = Path(new_val)
                    elif field_name == "edit_logo":
                        self.metadata_manager.metadata_cache.update_game_properties(selected_game.id, logo=new_val)
                        selected_game.logo = Path(new_val)
                    elif field_name == "edit_hero":
                        self.metadata_manager.metadata_cache.update_game_properties(selected_game.id, hero=new_val)
                        selected_game.hero = Path(new_val)
                continue

            if action_name == "toggle_favorite":
                new_state = self.metadata_manager.toggle_favorite(selected_game.id)
                selected_game.favorite = new_state
                games = sort_games_with_recents(games, recent_limit=recent_limit)
                logger.info("Toggled favorite for '%s' -> %s", selected_game.name, new_state)
                continue

            if action_name == "show_details":
                details_provider = GameDetailsProvider(metadata_cache=self.metadata_manager.metadata_cache)
                details = details_provider.get_details(selected_game)
                if details is not None and self.ui is not None:
                    self.ui.show_game_details_dialog(details.formatted_summary(), selected_game.name)
                continue

            if action_name == "refresh_metadata":
                logger.info("Refreshing metadata and artwork for '%s'", selected_game.name)
                self.metadata_manager.enrich(selected_game)
                # Force SteamGridDB artwork download for all art types if API key is configured
                if (
                    self.metadata_manager.steamgriddb is not None
                    and self.metadata_manager.steamgriddb.is_available()
                ):
                    self.metadata_manager.steamgriddb.fetch_game_artwork_background(selected_game)
                    logger.info("SteamGridDB artwork download queued for '%s'", selected_game.name)
                else:
                    logger.info(
                        "SteamGridDB not configured — set STEAMGRIDDB_API_KEY env var to enable artwork downloads"
                    )
                continue

            if action_name == "remove_from_library":
                logger.info("Removing game '%s' [%s] from library", selected_game.name, selected_game.id)
                if action_obj is not None:
                    action_obj.execute(selected_game)
                games = [g for g in games if g.id != selected_game.id]
                continue

            if action_name == "execute_action" and action_obj is not None:
                logger.info("Executing custom dynamic action '%s' for game '%s'", action_obj.label, selected_game.name)
                try:
                    action_obj.execute(selected_game)
                except Exception as err:
                    logger.error("Action '%s' failed: %s", action_obj.label, err)
                continue

            # Launch selected game and record launch statistics
            logger.info("Launching selected game: %s [%s]", selected_game.name, selected_game.id)
            try:
                launch(selected_game)
                self.metadata_manager.record_launch(selected_game.id)
            except Exception as err:
                logger.error("Failed to launch '%s': %s", selected_game.name, err)
                print(f"GameDeck Launch Error: Failed to launch '{selected_game.name}': {err}", file=sys.stderr)
                return 1

            return 0


def main() -> None:
    """Application main entry point.

    Reads ``GAMEDECK_LOG_LEVEL`` from the environment to override the default
    ``INFO`` logging level.  Valid values are the standard Python level names:
    ``DEBUG``, ``INFO``, ``WARNING``, ``ERROR``, ``CRITICAL``.
    """
    import os

    log_level_name = os.environ.get("GAMEDECK_LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s (pid=%(process)d): %(message)s",
    )
    logger.debug("GameDeck v0.5.0 starting up")
    app = GameDeck()
    sys.exit(app.run(sys.argv[1:]))
