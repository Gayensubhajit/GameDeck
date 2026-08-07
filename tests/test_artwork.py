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

    def test_non_blocking_fetch_async(self) -> None:
        """Verify that fetch_async submits background download without blocking execution."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir) / "artwork"
            cache = ArtworkCache(cache_dir=cache_dir)

            with patch("urllib.request.urlopen") as mock_urlopen:
                mock_resp = MagicMock()
                mock_resp.headers.get.return_value = "image/jpeg"
                mock_resp.read.return_value = b"DOWNLOADED_ARTWORK"
                mock_resp.__enter__.return_value = mock_resp
                mock_urlopen.return_value = mock_resp

                # Calling fetch_async must return immediately (non-blocking)
                cache.fetch_async("steam_730", "heroes", "https://example.com/hero.jpg")

                # Allow worker thread to complete
                cache._executor.shutdown(wait=True)

                downloaded = cache.get_artwork("steam_730", "heroes")
                self.assertIsNotNone(downloaded)


if __name__ == "__main__":
    unittest.main()
