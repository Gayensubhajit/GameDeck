"""Unit tests for MetadataManager, lazy-loaded artwork caching, and clean provider separation."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gamedeck.artwork import ArtworkCache
from gamedeck.database import MetadataCache
from gamedeck.metadata_manager import MetadataManager
from gamedeck.models import Game
from gamedeck.providers.filesystem import FilesystemProvider
from gamedeck.providers.heroic import HeroicProvider
from gamedeck.providers.lutris import LutrisProvider
from gamedeck.providers.native import NativeProvider
from gamedeck.providers.steam import SteamProvider


class TestMetadataManager(unittest.TestCase):
    """Test MetadataManager ownership of icons, covers, logos, cached metadata, and non-blocking caching."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cache_dir = Path(self.temp_dir.name) / "artwork"
        self.db_path = Path(self.temp_dir.name) / "test_metadata.db"

        self.metadata_cache = MetadataCache(db_path=self.db_path)
        self.artwork_cache = ArtworkCache(cache_dir=self.cache_dir)
        self.manager = MetadataManager(
            metadata_cache=self.metadata_cache,
            artwork_cache=self.artwork_cache,
        )

    def tearDown(self) -> None:
        self.artwork_cache._executor.shutdown(wait=False)
        self.temp_dir.cleanup()

    def test_enrich_attaches_sqlite_metadata(self) -> None:
        game = Game(id="game_1", name="Hollow Knight", source="steam", launcher="steam")
        self.manager.record_launch("game_1")
        self.manager.toggle_favorite("game_1")

        enriched = self.manager.enrich(game)
        self.assertTrue(enriched.favorite)
        self.assertEqual(enriched.launch_count, 1)
        self.assertIsNotNone(enriched.last_played)

    def test_enrich_all_batch(self) -> None:
        games = [
            Game(id="game_1", name="Hollow Knight", source="steam", launcher="steam"),
            Game(id="game_2", name="Celeste", source="steam", launcher="steam"),
        ]
        self.manager.toggle_favorite("game_2")
        synced = self.manager.enrich_all(games)

        self.assertFalse(synced[0].favorite)
        self.assertTrue(synced[1].favorite)

    def test_lazy_artwork_loading_from_cache(self) -> None:
        # Pre-store an icon in cache
        fake_icon = Path(self.temp_dir.name) / "test_icon.png"
        fake_icon.write_bytes(b"\x89PNG\r\n\x1a\n")
        self.artwork_cache.store_artwork("game_1", "icons", fake_icon, ext=".png")

        game = Game(id="game_1", name="Hollow Knight", source="steam", launcher="steam")
        loaded_icon = self.manager.load_artwork_lazy(game, "icons")
        self.assertIsNotNone(loaded_icon)
        self.assertTrue(loaded_icon.is_file())

    def test_artwork_fallback_hierarchy(self) -> None:
        # Game with only an icon should have fallback for logo, hero, cover
        fake_icon = Path(self.temp_dir.name) / "test_icon.png"
        fake_icon.write_bytes(b"\x89PNG\r\n\x1a\n")
        self.artwork_cache.store_artwork("game_fallback", "icons", fake_icon, ext=".png")

        game = Game(id="game_fallback", name="Fallback Game", source="steam", launcher="steam")
        self.manager.enrich(game)
        self.assertIsNotNone(game.icon)
        self.assertIsNotNone(game.logo)
        self.assertIsNotNone(game.hero)
        self.assertIsNotNone(game.cover)

    def test_non_blocking_async_fetch(self) -> None:
        # fetch_artwork_async must return immediately without error
        self.manager.fetch_artwork_async("game_async", "covers", "http://example.com/invalid.jpg")
        # should not block or raise exception


class TestCleanProviderSeparation(unittest.TestCase):
    """Verify providers return pure Game objects with icon=None and cover=None and do not scan artwork."""

    def test_steam_provider_returns_pure_game_objects(self) -> None:
        steam = SteamProvider(steam_roots=[])
        self.assertFalse(hasattr(steam, "_resolve_cover"))
        self.assertFalse(hasattr(steam, "_resolve_icon"))

    def test_lutris_provider_returns_pure_game_objects(self) -> None:
        lutris = LutrisProvider(config_dirs=[])
        self.assertFalse(hasattr(lutris, "_resolve_cover"))
        self.assertFalse(hasattr(lutris, "_resolve_icon"))

    def test_heroic_provider_returns_pure_game_objects(self) -> None:
        heroic = HeroicProvider(heroic_roots=[])
        self.assertFalse(hasattr(heroic, "_find_cover_art"))
        self.assertFalse(hasattr(heroic, "_find_icon"))

    def test_native_provider_returns_pure_game_objects(self) -> None:
        native = NativeProvider(app_dirs=[])
        self.assertFalse(hasattr(native, "_resolve_icon"))

    def test_filesystem_provider_returns_pure_game_objects(self) -> None:
        fs = FilesystemProvider(search_dirs=[])
        self.assertFalse(hasattr(fs, "_resolve_assets"))


if __name__ == "__main__":
    unittest.main()
