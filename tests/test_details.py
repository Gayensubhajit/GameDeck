"""Unit tests for the Game Details system and on-demand metadata retrieval."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gamedeck.database import MetadataCache
from gamedeck.details import GameDetails, GameDetailsProvider
from gamedeck.models import Game


class TestGameDetailsSystem(unittest.TestCase):
    """Test GameDetails generation, cached metadata extraction, and zero duplicate scanning."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.cache = MetadataCache(db_path=self.root / "metadata.db")
        self.provider = GameDetailsProvider(metadata_cache=self.cache)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_details_from_game_instance(self) -> None:
        """Verify GameDetails generation from in-memory Game model."""
        exe_file = self.root / "Games" / "EldenRing" / "eldenring.exe"
        exe_file.parent.mkdir(parents=True, exist_ok=True)
        exe_file.write_bytes(b"exe")

        game = Game(
            id="steam_1245620",
            name="Elden Ring",
            source="steam",
            launcher="steam",
            executable=exe_file,
            appid="1245620",
            favorite=True,
            launch_count=12,
            last_played="2026-08-08T10:00:00Z",
        )

        details = self.provider.get_details(game)
        self.assertIsNotNone(details)
        self.assertEqual(details.title, "Elden Ring")
        self.assertEqual(details.source, "steam")
        self.assertEqual(details.provider_name, "Steam")
        self.assertEqual(details.launcher, "steam")
        self.assertEqual(details.install_path, exe_file.parent)
        self.assertEqual(details.executable, exe_file)
        self.assertEqual(details.launch_count, 12)
        self.assertEqual(details.last_played, "2026-08-08T10:00:00Z")
        self.assertTrue(details.favorite)

    def test_details_from_sqlite_cache_by_id(self) -> None:
        """Verify on-demand details lookup from SQLite without rescanning providers."""
        exe_file = self.root / "Games" / "Cyberpunk" / "Cyberpunk2077.exe"
        exe_file.parent.mkdir(parents=True, exist_ok=True)
        exe_file.write_bytes(b"cyberpunk")

        game = Game(
            id="heroic_cyberpunk",
            name="Cyberpunk 2077",
            source="heroic",
            launcher="heroic",
            executable=exe_file,
            appid="cyberpunk",
            favorite=False,
            launch_count=3,
        )

        # Save to SQLite cached_games
        self.cache.save_cached_games_for_provider("heroic", [game])

        # Retrieve details by ID string
        details = self.provider.get_details("heroic_cyberpunk")
        self.assertIsNotNone(details)
        self.assertEqual(details.title, "Cyberpunk 2077")
        self.assertEqual(details.source, "heroic")
        self.assertEqual(details.provider_name, "Heroic Games Launcher")
        self.assertEqual(details.launcher, "heroic")
        self.assertEqual(details.install_path, exe_file.parent)

    def test_formatted_summary(self) -> None:
        """Verify formatted summary text includes all required fields."""
        game = Game(
            id="lutris_bmw",
            name="Black Myth: Wukong",
            source="lutris",
            launcher="lutris",
            appid="bmw",
        )
        details = self.provider.get_details(game)
        summary = details.formatted_summary()
        self.assertIn("Title:        Black Myth: Wukong", summary)
        self.assertIn("Source:       lutris (Lutris)", summary)
        self.assertIn("Launcher:     lutris", summary)
        self.assertIn("Favorite:     No", summary)

    def test_formatted_panel(self) -> None:
        """Verify formatted panel includes all 15 metadata fields."""
        game = Game(
            id="lutris_bmw",
            name="Black Myth: Wukong",
            source="lutris",
            launcher="lutris",
            appid="bmw",
            favorite=True,
            playtime_minutes=145,
        )
        details = self.provider.get_details(game)
        panel = details.formatted_panel()
        self.assertIn("Black Myth: Wukong", panel)
        self.assertIn("[LUTRIS]", panel)
        self.assertIn("Playtime:</b> 2h 25m", panel)
        self.assertIn("Favorite:</b> ★ Yes", panel)
        self.assertIn("Hero:</b>", panel)
        self.assertIn("Logo:</b>", panel)

    def test_format_header_pango_with_hero_and_logo(self) -> None:
        """Verify premium information header displays all required fields with artwork."""
        hero_file = self.root / "hero.jpg"
        hero_file.write_bytes(b"hero")
        logo_file = self.root / "logo.png"
        logo_file.write_bytes(b"logo")

        game = Game(
            id="steam_cyberpunk",
            name="Cyberpunk 2077",
            source="steam",
            launcher="steam",
            appid="1091500",
            favorite=True,
            playtime_minutes=360,
            launch_count=25,
            last_played="2026-08-08T20:00:00Z",
            hero=hero_file,
            logo=logo_file,
            platform="Linux Native",
            wine_version="Proton 9.0",
        )
        details = self.provider.get_details(game)
        header = details.format_header_pango()

        # Large Title & Logo
        self.assertIn("Cyberpunk 2077", header)
        self.assertIn("logo.png", header)
        # Badges
        self.assertIn("[STEAM]", header)
        self.assertIn("[LINUX NATIVE]", header)
        self.assertIn("[PROTON 9.0]", header)
        self.assertIn("[v1.0]", header)
        self.assertIn("★ FAVORITE", header)
        # Small metadata
        self.assertIn("6h 0m", header)
        self.assertIn("2026-08-08", header)
        self.assertIn("25", header)
        # Hero Artwork
        self.assertIn("hero.jpg", header)

    def test_format_header_pango_fallback_without_artwork(self) -> None:
        """Verify fallback behavior displays Game Icon, gradient indicator, and Title when artwork is missing."""
        icon_file = self.root / "game_icon.png"
        icon_file.write_bytes(b"icon")

        game = Game(
            id="lutris_indie",
            name="Hollow Knight",
            source="lutris",
            launcher="lutris",
            favorite=False,
            playtime_minutes=45,
            launch_count=2,
            icon=icon_file,
        )
        details = self.provider.get_details(game)
        header = details.format_header_pango()

        # Title
        self.assertIn("Hollow Knight", header)
        # Badges
        self.assertIn("[LUTRIS]", header)
        self.assertIn("☆ STANDARD", header)
        # Fallback Icon & Gradient Banner indicator (never looks empty)
        self.assertIn("Game Icon:</b>", header)
        self.assertIn("Gradient Glassmorphism Active", header)
        # Metadata
        self.assertIn("45m", header)
        self.assertIn("2", header)

    def test_unknown_game_returns_none(self) -> None:
        """Verify querying non-existent game ID returns None gracefully."""
        details = self.provider.get_details("non_existent_game_id")
        self.assertIsNone(details)


if __name__ == "__main__":
    unittest.main()
