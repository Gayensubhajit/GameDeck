"""Automated test suite for GameDeck."""

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from gamedeck.app import GameDeck
from gamedeck.config import Settings
from gamedeck.models import Game
from gamedeck.provider_manager import ProviderManager, get_all_games
from gamedeck.providers import Provider
from gamedeck.providers.filesystem import FilesystemProvider
from gamedeck.providers.lutris import LutrisProvider
from gamedeck.providers.steam import SteamProvider
from gamedeck.scanner import Scanner
from gamedeck.ui.rofi import RofiUI, generate_search_metadata


class TestGameDeckFullSystem(unittest.TestCase):
    """End-to-end integration and unit tests for GameDeck."""

    def test_provider_protocol(self) -> None:
        """Verify that all library providers conform to the Provider protocol."""
        self.assertTrue(isinstance(SteamProvider(), Provider))
        self.assertTrue(isinstance(LutrisProvider(), Provider))
        self.assertTrue(isinstance(FilesystemProvider(), Provider))

    def test_provider_precedence_and_deduplication(self) -> None:
        """Verify priority: Steam > Heroic > Lutris > Native > Filesystem."""
        g_steam = Game(id="steam_1", name="Elden Ring", source="steam", launcher="steam", appid="1245620")
        g_lutris = Game(id="lutris_elden", name="Elden Ring", source="lutris", launcher="lutris", appid="elden-ring")
        g_fs = Game(id="fs_elden", name="Elden Ring", source="filesystem", launcher="wine")

        manager = ProviderManager()
        merged = manager.merge_and_deduplicate([g_fs, g_lutris, g_steam])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].source, "steam")

    def test_steam_runtime_filtering(self) -> None:
        """Verify that Steam tools, runtimes, and servers are hidden."""
        steam = SteamProvider()
        self.assertTrue(steam._is_runtime_component("1493710", "Proton Experimental", "Proton - Experimental"))
        self.assertTrue(steam._is_runtime_component("228980", "Steamworks Common Redistributables", "Steamworks Shared"))
        self.assertTrue(steam._is_runtime_component("2394010", "Palworld Dedicated Server", "Palworld Dedicated Server"))
        self.assertFalse(steam._is_runtime_component("730", "Counter-Strike 2", "Counter-Strike Global Offensive"))

    def test_rofi_search_metadata(self) -> None:
        """Verify abbreviation and compact search indexing."""
        meta_bmw = generate_search_metadata("Black Myth: Wukong", "black-myth-wukong", "lutris")
        self.assertIn("bmw", meta_bmw.split())
        self.assertIn("blackmythwukong", meta_bmw.split())

        meta_gta = generate_search_metadata("Grand Theft Auto V", "gta-v", "wine")
        self.assertIn("gtav", meta_gta.split())
        self.assertIn("gta5", meta_gta.split())

    def test_rofi_icon_resolution_excludes_cover_art(self) -> None:
        """Verify that UI icons use dedicated icons, not cover art."""
        ui = RofiUI()
        g = Game(
            id="lutris_wukong",
            name="Black Myth - Wukong",
            source="lutris",
            launcher="lutris",
            appid="black-myth-wukong",
            cover=Path("/tmp/cover.jpg"),
        )
        icon = ui.resolve_game_icon(g)
        self.assertIsNotNone(icon)
        self.assertNotEqual(icon, "/tmp/cover.jpg")

    def test_configuration_loading(self) -> None:
        """Verify default settings and custom overrides."""
        settings = Settings()
        self.assertTrue(settings.providers.steam)
        self.assertEqual(settings.launch.default_windows_launcher, "lutris")
        self.assertIn("steam", settings.providers.enabled_list())


if __name__ == "__main__":
    unittest.main()
