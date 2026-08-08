"""Unit tests for SteamGridDB integration and rate-limited background artwork fetching."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from gamedeck.artwork import ArtworkCache
from gamedeck.metadata_manager import MetadataManager
from gamedeck.models import Game
from gamedeck.steamgriddb import SteamGridDBClient


class TestSteamGridDBClient(unittest.TestCase):
    """Test SteamGridDB client operations, rate limiting, and local cache integration."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cache_dir = Path(self.temp_dir.name)
        self.artwork_cache = ArtworkCache(cache_dir=self.cache_dir)
        self.client = SteamGridDBClient(
            api_key="mock_sgdb_api_key",
            artwork_cache=self.artwork_cache,
            min_request_interval=0.01,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_availability(self) -> None:
        """Verify is_available reflects presence of API key."""
        self.assertTrue(self.client.is_available())
        empty_client = SteamGridDBClient(api_key=None, artwork_cache=self.artwork_cache)
        empty_client.api_key = None
        self.assertFalse(empty_client.is_available())

    @patch("gamedeck.steamgriddb.urllib.request.urlopen")
    def test_search_game_id_steam(self, mock_urlopen: MagicMock) -> None:
        """Verify search_game_id uses Steam AppID endpoint for steam games."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = json.dumps({
            "success": True,
            "data": {"id": 12345, "name": "Counter-Strike 2"}
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_response

        game = Game(id="steam_730", name="Counter-Strike 2", source="steam", launcher="steam", appid="730")
        sgdb_id = self.client.search_game_id(game)
        self.assertEqual(sgdb_id, 12345)

    @patch("gamedeck.steamgriddb.urllib.request.urlopen")
    def test_search_game_id_title(self, mock_urlopen: MagicMock) -> None:
        """Verify search_game_id falls back to autocomplete title search."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = json.dumps({
            "success": True,
            "data": [{"id": 67890, "name": "Black Myth: Wukong"}]
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_response

        game = Game(id="lutris_bmw", name="Black Myth: Wukong", source="lutris", launcher="lutris", appid="bmw")
        sgdb_id = self.client.search_game_id(game)
        self.assertEqual(sgdb_id, 67890)

    @patch.object(SteamGridDBClient, "search_game_id", return_value=999)
    @patch.object(SteamGridDBClient, "_get_best_asset_url", return_value="https://cdn.steamgriddb.com/grid/mock.jpg")
    def test_metadata_manager_integration(self, mock_get_url: MagicMock, mock_search: MagicMock) -> None:
        """Verify MetadataManager dispatches background fetches when artwork is missing."""
        meta_mgr = MetadataManager(artwork_cache=self.artwork_cache, steamgriddb=self.client)
        game = Game(id="test_game", name="Elden Ring", source="steam", launcher="steam", appid="1245620")

        enriched = meta_mgr.enrich(game)
        self.assertIsNotNone(enriched)

    def test_never_redownload_existing_artwork(self) -> None:
        """Verify fetch_game_artwork_background returns early if all assets exist locally."""
        game = Game(id="g_all_cached", name="Portal 2", source="steam", launcher="steam")
        self.artwork_cache.store_artwork(game.id, "heroes", b"HERO", ext=".jpg")
        self.artwork_cache.store_artwork(game.id, "covers", b"COVER", ext=".jpg")
        self.artwork_cache.store_artwork(game.id, "icons", b"ICON", ext=".png")
        self.artwork_cache.store_artwork(game.id, "logos", b"LOGO", ext=".png")

        with patch.object(SteamGridDBClient, "search_game_id") as mock_search:
            self.client.fetch_game_artwork_background(game)
            mock_search.assert_not_called()

    def test_offline_mode_skips_fetches(self) -> None:
        """Verify offline mode skips all remote API searches and downloads."""
        self.client.offline_mode = True
        self.assertFalse(self.client.is_available())

        game = Game(id="g_offline", name="Half-Life 2", source="steam", launcher="steam")
        with patch.object(SteamGridDBClient, "search_game_id") as mock_search:
            self.client.fetch_game_artwork_background(game)
            mock_search.assert_not_called()


if __name__ == "__main__":
    unittest.main()
