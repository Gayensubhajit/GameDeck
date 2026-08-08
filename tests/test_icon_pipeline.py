"""Unit tests verifying the strict icon resolution pipeline and native provider icon preservation."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from gamedeck.artwork import ArtworkCache
from gamedeck.database import MetadataCache
from gamedeck.metadata_manager import MetadataManager
from gamedeck.models import Game
from gamedeck.providers.heroic import HeroicProvider
from gamedeck.providers.lutris import LutrisProvider
from gamedeck.providers.native import NativeProvider
from gamedeck.providers.steam import SteamProvider


class TestIconResolutionPipeline(unittest.TestCase):
    """Test icon pipeline priority, provider icon discovery, and non-destructive metadata updates."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.artwork_cache_dir = self.root / "artwork"
        self.artwork_cache = ArtworkCache(cache_dir=self.artwork_cache_dir)
        self.metadata_cache = MetadataCache(db_path=self.root / "metadata.db")
        self.manager = MetadataManager(
            metadata_cache=self.metadata_cache,
            artwork_cache=self.artwork_cache,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_custom_cached_icon_priority(self) -> None:
        """Priority 1: Downloaded/custom cached icon overrides provider icon if present."""
        custom_icon_path = self.root / "custom.png"
        custom_icon_path.write_bytes(b"custom_icon_data")

        # Save to ArtworkCache
        self.artwork_cache.store_artwork("game_1", "icons", custom_icon_path, ext=".png")

        provider_icon = self.root / "provider_icon.png"
        provider_icon.write_bytes(b"provider_icon_data")

        game = Game(
            id="game_1",
            name="Test Game",
            source="steam",
            launcher="steam",
            icon=provider_icon,
        )

        enriched = self.manager.resolve_artwork(game)
        self.assertEqual(enriched.icon, self.artwork_cache_dir / "icons" / "game_1.png")

    def test_native_steam_icon_retained(self) -> None:
        """Priority 2: Steam native icon is preserved and never overwritten by fallback."""
        steam_icon = self.root / "steam_icon_10.png"
        steam_icon.write_bytes(b"steam_icon")

        game = Game(
            id="steam_10",
            name="Counter-Strike",
            source="steam",
            launcher="steam",
            icon=steam_icon,
            appid="10",
        )

        enriched = self.manager.resolve_artwork(game)
        self.assertEqual(enriched.icon, steam_icon)

    def test_native_lutris_icon_retained(self) -> None:
        """Priority 2: Lutris native icon is preserved when no custom artwork exists."""
        lutris_icon = self.root / "lutris_wukong.png"
        lutris_icon.write_bytes(b"lutris_icon")

        game = Game(
            id="lutris_bmw",
            name="Black Myth: Wukong",
            source="lutris",
            launcher="lutris",
            icon=lutris_icon,
            appid="bmw",
        )

        enriched = self.manager.resolve_artwork(game)
        self.assertEqual(enriched.icon, lutris_icon)

    def test_native_heroic_icon_retained(self) -> None:
        """Priority 2: Heroic native icon is retained during metadata refresh."""
        heroic_icon = self.root / "heroic_cyberpunk.png"
        heroic_icon.write_bytes(b"heroic_icon")

        game = Game(
            id="heroic_cyberpunk",
            name="Cyberpunk 2077",
            source="heroic",
            launcher="heroic",
            icon=heroic_icon,
            appid="cyberpunk",
        )

        enriched = self.manager.resolve_artwork(game)
        self.assertEqual(enriched.icon, heroic_icon)

    def test_native_desktop_icon_retained(self) -> None:
        """Priority 2: Native Linux .desktop icon is preserved during metadata synchronization."""
        desktop_icon = self.root / "kblackbox.png"
        desktop_icon.write_bytes(b"kblackbox_icon")

        game = Game(
            id="native_kblackbox",
            name="KBlackBox",
            source="native",
            launcher="native",
            icon=desktop_icon,
            appid="kblackbox",
        )

        enriched = self.manager.resolve_artwork(game)
        self.assertEqual(enriched.icon, desktop_icon)

    def test_fallback_used_only_when_no_icon_exists(self) -> None:
        """Priority 4: Fallback hierarchy kicks in only when no native or cached icon exists."""
        game = Game(
            id="game_without_icon",
            name="Simple Game",
            source="filesystem",
            launcher="wine",
            icon=None,
            cover=None,
            logo=None,
            hero=None,
        )

        enriched = self.manager.resolve_artwork(game)
        # Icon remains None so the UI layer uses its theme/generic fallback without replacing valid icons
        self.assertIsNone(enriched.icon)

    def test_metadata_refresh_preserves_icons(self) -> None:
        """Verify that multiple sync cycles and metadata updates never remove or erase icons."""
        native_icon = self.root / "app.png"
        native_icon.write_bytes(b"app_icon")

        game = Game(
            id="game_cycle",
            name="Cycle Game",
            source="native",
            launcher="native",
            icon=native_icon,
            favorite=True,
        )

        # Initial sync
        self.manager.enrich(game)
        self.assertEqual(game.icon, native_icon)

        # Second sync with new instance representing rescan
        game2 = Game(
            id="game_cycle",
            name="Cycle Game",
            source="native",
            launcher="native",
            icon=native_icon,
        )
        self.manager.enrich(game2)
        self.assertEqual(game2.icon, native_icon)
        self.assertTrue(game2.favorite)


if __name__ == "__main__":
    unittest.main()
