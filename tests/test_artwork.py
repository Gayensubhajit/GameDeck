"""Unit and integration tests for local ArtworkCache and asset resolution."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from gamedeck.artwork import ArtworkCache, ARTWORK_TYPES
from gamedeck.models import Game


class TestArtworkCache(unittest.TestCase):
    """Test suite for ArtworkCache storage, non-blocking fetching, and fallback resolution."""

    def test_cache_directories_initialized(self) -> None:
        """Verify that cache subdirectories are created for all supported artwork types."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir) / "artwork"
            cache = ArtworkCache(cache_dir=cache_dir)

            for art_type in ("icons", "logos", "heroes", "covers"):
                self.assertTrue((cache_dir / art_type).is_dir())

    def test_store_and_get_artwork(self) -> None:
        """Verify storing raw bytes and file paths in the artwork cache."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir) / "artwork"
            cache = ArtworkCache(cache_dir=cache_dir)

            game_id = "steam_1245620"
            dummy_bytes = b"IMAGE_DATA_BYTES"

            # Store cover
            saved_path = cache.store_artwork(game_id, "covers", dummy_bytes, ext=".jpg")
            self.assertTrue(saved_path.is_file())
            self.assertEqual(saved_path.read_bytes(), dummy_bytes)

            # Retrieve cover
            retrieved = cache.get_artwork(game_id, "covers")
            self.assertIsNotNone(retrieved)
            self.assertEqual(retrieved, saved_path)

    def test_graceful_fallbacks_to_available_assets(self) -> None:
        """Verify that missing artwork falls back gracefully in the asset hierarchy."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir) / "artwork"
            cache = ArtworkCache(cache_dir=cache_dir)

            icon_path = Path(tmpdir) / "game_icon.png"
            icon_path.write_bytes(b"ICON")

            # Game has only an icon, no logo, hero, or cover
            game = Game(
                id="native_mari0",
                name="mari0",
                source="native",
                launcher="native",
                icon=icon_path,
            )

            resolved_game = cache.resolve_artwork(game)

            # Icon remains unchanged
            self.assertEqual(resolved_game.icon, icon_path)
            # Logo falls back to icon
            self.assertEqual(resolved_game.logo, icon_path)
            # Hero falls back to icon
            self.assertEqual(resolved_game.hero, icon_path)
            # Cover falls back to icon
            self.assertEqual(resolved_game.cover, icon_path)

    def test_has_artwork_and_never_redownload(self) -> None:
        """Verify has_artwork returns True for cached files and skips redundant downloads."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir) / "artwork"
            cache = ArtworkCache(cache_dir=cache_dir)

            game_id = "lutris_bmw"
            self.assertFalse(cache.has_artwork(game_id, "heroes"))

            cache.store_artwork(game_id, "heroes", b"HERO_DATA", ext=".jpg")
            self.assertTrue(cache.has_artwork(game_id, "heroes"))

            # Calling fetch_async when already cached does not make network requests
            with patch("urllib.request.urlopen") as mock_urlopen:
                cache.fetch_async(game_id, "heroes", "https://example.com/hero.jpg")
                mock_urlopen.assert_not_called()

    def test_offline_mode_prevents_network_calls(self) -> None:
        """Verify offline_mode prevents all remote network requests."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir) / "artwork"
            cache = ArtworkCache(cache_dir=cache_dir, offline_mode=True)

            with patch("urllib.request.urlopen") as mock_urlopen:
                cache.fetch_async("steam_400", "heroes", "https://example.com/hero.jpg")
                mock_urlopen.assert_not_called()

    def test_generate_placeholder_instant_and_nonblocking(self) -> None:
        """Verify clean SVG placeholder generation for offline/pending artwork."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir) / "artwork"
            cache = ArtworkCache(cache_dir=cache_dir)

            game = Game(id="steam_888", name="Cyberpunk 2077", source="steam", launcher="steam")
            placeholder_path = cache.generate_placeholder(game)

            self.assertTrue(placeholder_path.is_file())
            content = placeholder_path.read_text(encoding="utf-8")
            self.assertIn("<svg", content)
            self.assertIn("Cyberpunk 2077", content)
            self.assertIn("STEAM", content)


if __name__ == "__main__":
    unittest.main()
