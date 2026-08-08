"""Unit tests for GameDeck Next-Gen platform features (EventBus, Plugins, Saves, Screenshots, API, CLI)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gamedeck.api import GameDeckAPI, get_api
from gamedeck.events import EventBus, FavoriteChanged, GameAdded, get_event_bus
from gamedeck.models import Game
from gamedeck.plugins import BaseProviderPlugin, PluginRegistry, get_plugin_registry
from gamedeck.profiles import LaunchProfile
from gamedeck.saves import SaveBackup, SaveManager
from gamedeck.screenshots import ScreenshotManager
from gamedeck.stats import LibraryStatsProvider


class DummyPlugin(BaseProviderPlugin):
    name = "dummy"
    display_name = "Dummy Plugin"

    def is_available(self) -> bool:
        return True

    def scan(self) -> list[Game]:
        return [Game(id="dummy_1", name="Dummy Game", source="dummy")]


class TestNextGenFeatures(unittest.TestCase):
    """Test suite for Next-Gen architecture components."""

    def test_event_bus_publish_subscribe(self) -> None:
        bus = EventBus()
        received: list[FavoriteChanged] = []

        def handler(event: FavoriteChanged) -> None:
            received.append(event)

        bus.subscribe(FavoriteChanged, handler)
        evt = FavoriteChanged(game_id="game_1", favorite=True)
        bus.publish(evt)

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].game_id, "game_1")
        self.assertTrue(received[0].favorite)

    def test_plugin_registry(self) -> None:
        registry = PluginRegistry()
        dummy = DummyPlugin()
        registry.register_provider(dummy)

        fetched = registry.get_provider("dummy")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.display_name, "Dummy Plugin")
        self.assertEqual(len(registry.get_all_providers()), 1)

    def test_save_manager_backup_restore(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            save_dir = Path(tmpdir) / "saves"
            save_dir.mkdir(parents=True)
            (save_dir / "save1.dat").write_text("DATA_CONTENT", encoding="utf-8")

            game = Game(id="test_game", name="Test Game", source="native", launcher="native")
            mgr = SaveManager()

            with unittest.mock.patch.object(SaveManager, "get_backup_dir", return_value=Path(tmpdir)):
                backup = mgr.create_backup(game, save_dir, notes="Initial Save")
                self.assertIsNotNone(backup)
                self.assertTrue(backup.archive_path.exists())

                restore_dir = Path(tmpdir) / "restored"
                success = mgr.restore_backup(backup, restore_dir)
                self.assertTrue(success)
                self.assertTrue((restore_dir / "saves" / "save1.dat").exists())

    def test_launch_profile_wrappers(self) -> None:
        profile = LaunchProfile(
            id="prof_1",
            game_id="game_1",
            name="Performance Profile",
            launcher="native",
            use_mangohud=True,
            use_obs_vkcapture=True,
            use_gamemode=False,
            use_gamescope=False,
        )
        self.assertTrue(profile.use_mangohud)
        self.assertTrue(profile.use_obs_vkcapture)

    def test_public_api(self) -> None:
        api = get_api()
        self.assertIsInstance(api, GameDeckAPI)
        games = api.get_games()
        self.assertIsInstance(games, list)

    def test_screenshot_manager(self) -> None:
        mgr = ScreenshotManager()
        game = Game(id="test_game", name="Test Game", source="native", launcher="native")
        scs = mgr.discover_screenshots(game)
        self.assertIsInstance(scs, list)
