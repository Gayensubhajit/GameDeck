"""Unit tests for SQLite LibraryCache, incremental provider scanning, provider modification detection, and schema migrations."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from gamedeck.database import CachedGame, GameMetadata, LibraryCache, MetadataCache
from gamedeck.models import Game
from gamedeck.provider_manager import ProviderManager
from gamedeck.providers.steam import SteamProvider


class TestLibraryCacheAndMigrations(unittest.TestCase):
    """Test SQLite LibraryCache persistence, schema migrations, and change detection."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_library.db"
        self.cache = MetadataCache(db_path=self.db_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_schema_migrations_applied(self) -> None:
        """Verify schema_migrations table tracks applied version 1 and 2."""
        with self.cache._get_connection() as conn:
            cursor = conn.execute("SELECT version FROM schema_migrations ORDER BY version")
            versions = [row["version"] for row in cursor.fetchall()]
            self.assertIn(1, versions)
            self.assertIn(2, versions)

    def test_cached_games_table_crud(self) -> None:
        """Verify saving and retrieving cached games for a provider."""
        game = Game(
            id="steam_730",
            name="Counter-Strike 2",
            source="steam",
            launcher="steam",
            executable=Path("/usr/bin/cs2"),
            icon=Path("/icons/cs2.png"),
            logo=Path("/logos/cs2.png"),
            hero=Path("/heroes/cs2.png"),
            cover=Path("/covers/cs2.png"),
            installed=True,
            favorite=True,
            appid="730",
            last_played="2026-08-08T00:00:00Z",
            launch_count=5,
        )
        self.cache.save_cached_games_for_provider("steam", [game], fingerprint="fp_abc_123")

        cached = self.cache.get_cached_games_for_provider("steam")
        self.assertEqual(len(cached), 1)
        self.assertEqual(cached[0].id, "steam_730")
        self.assertEqual(cached[0].name, "Counter-Strike 2")
        self.assertEqual(cached[0].source, "steam")
        self.assertEqual(cached[0].launcher, "steam")
        self.assertEqual(cached[0].appid, "730")
        self.assertTrue(cached[0].favorite)
        self.assertEqual(cached[0].launch_count, 5)

    def test_provider_fingerprint_modification_detection(self) -> None:
        """Verify is_provider_modified returns True for cold start and False when fingerprint matches."""
        # Cold start
        self.assertTrue(self.cache.is_provider_modified("steam", "fp_111"))

        # Save fingerprint
        self.cache.set_provider_fingerprint("steam", "fp_111")
        self.assertFalse(self.cache.is_provider_modified("steam", "fp_111"))

        # Modified fingerprint
        self.assertTrue(self.cache.is_provider_modified("steam", "fp_222"))

    def test_incremental_scan_skips_unmodified_provider(self) -> None:
        """Verify ProviderManager uses cached games on subsequent runs when provider is unmodified."""
        steam_game = Game(
            id="steam_1",
            name="Incremental Steam Game",
            source="steam",
            launcher="steam",
            appid="1",
        )

        with patch.object(SteamProvider, "enabled", return_value=True):
            with patch.object(SteamProvider, "scan", return_value=[steam_game]) as mock_scan:
                manager = ProviderManager(
                    enabled_providers=["steam"],
                    metadata_cache=self.cache,
                )

                # 1. Cold start: full scan
                games_run1 = manager.get_games()
                self.assertEqual(len(games_run1), 1)
                self.assertEqual(mock_scan.call_count, 1)

                # 2. Later run: provider unmodified -> incremental scan hits cache, scan() not called
                mock_scan.reset_mock()
                games_run2 = manager.get_games()
                self.assertEqual(len(games_run2), 1)
                self.assertEqual(games_run2[0].name, "Incremental Steam Game")
                mock_scan.assert_not_called()

    def test_incremental_scan_rescans_modified_provider(self) -> None:
        """Verify ProviderManager rescans when provider fingerprint changes."""
        game_v1 = Game(id="steam_1", name="Steam Game V1", source="steam", launcher="steam")
        game_v2 = Game(id="steam_1", name="Steam Game V2", source="steam", launcher="steam")

        with patch.object(SteamProvider, "enabled", return_value=True):
            with patch.object(SteamProvider, "scan", side_effect=[[game_v1], [game_v2]]) as mock_scan:
                manager = ProviderManager(
                    enabled_providers=["steam"],
                    metadata_cache=self.cache,
                )

                # Cold start
                games1 = manager.get_games()
                self.assertEqual(games1[0].name, "Steam Game V1")

                # Force modification by altering stored fingerprint
                self.cache.set_provider_fingerprint("steam", "old_fp")

                # Run again: should rescan
                games2 = manager.get_games()
                self.assertEqual(games2[0].name, "Steam Game V2")
                self.assertEqual(mock_scan.call_count, 2)


if __name__ == "__main__":
    unittest.main()
