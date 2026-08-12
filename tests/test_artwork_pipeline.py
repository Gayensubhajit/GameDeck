"""Unit tests for the complete GameDeck Artwork Pipeline."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from gamedeck.artwork import ArtworkCache
from gamedeck.metadata_manager import MetadataManager
from gamedeck.models import Game
from gamedeck.steamgriddb import SteamGridDBClient
from gamedeck.ui.artwork_resolver import ArtworkResolver


class TestArtworkPipeline(unittest.TestCase):
    """Test suite covering artwork priority, caching, automatic downloads, lazy loading, and offline mode."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cache_dir = Path(self.temp_dir.name) / "artwork"
        self.artwork_cache = ArtworkCache(cache_dir=self.cache_dir)
        self.resolver = ArtworkResolver(cache_dir=self.cache_dir)
        self.client = SteamGridDBClient(api_key="mock_key", artwork_cache=self.artwork_cache)
        self.manager = MetadataManager(artwork_cache=self.artwork_cache, steamgriddb=self.client)

    def tearDown(self) -> None:
        self.artwork_cache._executor.shutdown(wait=False)
        self.temp_dir.cleanup()

    def test_artwork_priority_hierarchy(self) -> None:
        """Verify strict priority hierarchy: 1-Hero, 2-Cover, 3-Capsule, 4-Icon, 5-Placeholder."""
        game = Game(id="g_priority", name="Priority Test Game", source="steam", launcher="steam")

        # 5. Placeholder when no assets exist
        ph = self.resolver.resolve_primary_artwork(game)
        self.assertTrue(ph.endswith(".svg") or "applications-games" in ph)

        # 4. Executable Icon
        icon_path = self.artwork_cache.store_artwork(game.id, "icons", b"ICON", ext=".png")
        self.resolver.clear_cache(game.id)
        art4 = self.resolver.resolve_primary_artwork(game)
        self.assertEqual(art4, str(icon_path))

        # 3. Capsule
        capsule_path = self.artwork_cache.store_artwork(game.id, "capsules", b"CAPSULE", ext=".jpg")
        self.resolver.clear_cache(game.id)
        art3 = self.resolver.resolve_primary_artwork(game)
        self.assertEqual(art3, str(capsule_path))

        # 2. Portrait Cover
        cover_path = self.artwork_cache.store_artwork(game.id, "covers", b"COVER", ext=".jpg")
        self.resolver.clear_cache(game.id)
        art2 = self.resolver.resolve_primary_artwork(game)
        self.assertEqual(art2, str(cover_path))

        # 1. Hero Image overrides everything
        hero_path = self.artwork_cache.store_artwork(game.id, "heroes", b"HERO", ext=".jpg")
        self.resolver.clear_cache(game.id)
        art1 = self.resolver.resolve_primary_artwork(game)
        self.assertEqual(art1, str(hero_path))

    def test_cache_everything_and_never_redownload_existing(self) -> None:
        """Verify downloaded assets are cached locally and never re-downloaded unless forced."""
        game = Game(id="g_cached", name="Cached Game", source="steam", launcher="steam", appid="100")
        self.artwork_cache.store_artwork(game.id, "heroes", b"HERO", ext=".jpg")
        self.artwork_cache.store_artwork(game.id, "covers", b"COVER", ext=".jpg")
        self.artwork_cache.store_artwork(game.id, "icons", b"ICON", ext=".png")
        self.artwork_cache.store_artwork(game.id, "logos", b"LOGO", ext=".png")

        # Background fetch when everything exists should skip search
        with patch.object(SteamGridDBClient, "search_game_id") as mock_search:
            self.client.fetch_game_artwork_background(game, force=False)
            mock_search.assert_not_called()

    def test_lazy_loading_and_thumbnail_caching(self) -> None:
        """Verify load_artwork_lazy resolves images on demand without blocking."""
        game = Game(id="g_lazy", name="Lazy Game", source="steam", launcher="steam")
        saved_hero = self.artwork_cache.store_artwork(game.id, "heroes", b"HERO_DATA", ext=".jpg")

        hero = self.manager.load_artwork_lazy(game, "heroes")
        self.assertEqual(hero, saved_hero)

        # In-memory thumbnail cache in ArtworkResolver
        cached_art = self.resolver.resolve_primary_artwork(game)
        self.assertEqual(cached_art, str(saved_hero))
        self.assertIn("g_lazy:priority", self.resolver._thumbnail_cache)

    def test_offline_mode_uses_cached_artwork(self) -> None:
        """Verify offline mode skips network fetches and resolves cached files or SVG placeholder."""
        self.artwork_cache.offline_mode = True
        self.client.offline_mode = True

        game = Game(id="g_offline", name="Offline Title", source="steam", launcher="steam")
        # Ensure non-blocking background fetch returns early
        with patch.object(SteamGridDBClient, "search_game_id") as mock_search:
            self.client.fetch_game_artwork_background(game)
            mock_search.assert_not_called()

        art = self.resolver.resolve_primary_artwork(game)
        self.assertTrue(art.endswith(".svg") or "applications-games" in art)

    def test_metadata_refresh_forces_artwork_update(self) -> None:
        """Verify metadata refresh passes force=True to re-query and update artwork."""
        game = Game(id="g_refresh", name="Refresh Game", source="steam", launcher="steam", appid="500")
        self.artwork_cache.store_artwork(game.id, "covers", b"OLD_COVER", ext=".jpg")

        with patch.object(SteamGridDBClient, "_fetch_and_store_all") as mock_fetch:
            self.client.fetch_game_artwork_background(game, force=True)
            mock_fetch.assert_called_once_with(game, on_complete=None, force=True)


if __name__ == "__main__":
    unittest.main()
