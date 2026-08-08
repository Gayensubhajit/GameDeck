"""Unit tests for the redesigned GameDeck Rofi UI/UX enhancements."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from gamedeck.models import Game
from gamedeck.ui.rofi import (
    RofiUI,
    _calc_rofi_lines,
    generate_search_metadata,
)


class TestUIRedesign(unittest.TestCase):
    """Test suite for UI/UX redesign functionality."""

    def setUp(self) -> None:
        self.game_lutris = Game(
            id="lutris_bmw",
            name="Black Myth: Wukong",
            source="lutris",
            launcher="lutris",
            installed=True,
            favorite=True,
            launch_count=14,
            last_played="2026-08-05T21:30:00+00:00",
        )
        self.game_steam = Game(
            id="steam_730",
            name="Counter-Strike 2",
            source="steam",
            launcher="steam",
            installed=True,
            favorite=False,
        )

    def test_calc_rofi_lines(self) -> None:
        """Verify dynamic line calculation caps at max_lines and avoids zero."""
        self.assertEqual(_calc_rofi_lines(0), "1")
        self.assertEqual(_calc_rofi_lines(3), "3")
        self.assertEqual(_calc_rofi_lines(10), "10")
        self.assertEqual(_calc_rofi_lines(25), "12")
        self.assertEqual(_calc_rofi_lines(25, max_lines=15), "15")

    def test_generate_search_metadata_extended(self) -> None:
        """Verify search metadata includes tags, collections, favorite, and installed keywords."""
        meta = generate_search_metadata(
            name="Black Myth: Wukong",
            game=self.game_lutris,
            tags=["Soulslike", "RPG"],
            collections=["Favorites", "Action"],
        )
        self.assertIn("favorite", meta)
        self.assertIn("installed", meta)
        self.assertIn("soulslike", meta)
        self.assertIn("rpg", meta)

    def test_lutris_game_icon_resolution(self) -> None:
        """Verify Lutris source or runner game resolves to Lutris icon rather than generic Wine."""
        ui = RofiUI()
        g_wine_runner = Game(
            id="lutris_bmw",
            name="Black Myth - Wukong",
            source="lutris",
            launcher="wine",
            installed=True,
        )
        icon = ui.resolve_game_icon(g_wine_runner)
        self.assertNotEqual(icon, "wine")
        self.assertTrue("lutris" in icon.lower() or icon.endswith(".png") or icon.endswith(".svg"))


if __name__ == "__main__":
    unittest.main()
