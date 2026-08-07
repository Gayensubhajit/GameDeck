"""Unit and integration tests for SQLite metadata cache."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from gamedeck.database import MetadataCache
from gamedeck.models import Game


class TestMetadataCache(unittest.TestCase):
    """Test suite for SQLite metadata cache."""

    def test_schema_and_no_redundant_executable_storage(self) -> None:
        """Verify SQLite table schema and ensure executable paths are not stored."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "metadata.db"
            cache = MetadataCache(db_path=db_path)

            conn = sqlite3.connect(str(db_path))
            cursor = conn.execute("PRAGMA table_info(game_metadata)")
            columns = [row[1] for row in cursor.fetchall()]
            conn.close()

            self.assertIn("id", columns)
            self.assertIn("icon", columns)
            self.assertIn("cover", columns)
            self.assertIn("last_played", columns)
            self.assertIn("launch_count", columns)
            self.assertIn("favorite", columns)

            # Strict verification: executable paths must NOT be stored redundantly
            self.assertNotIn("executable", columns)
            self.assertNotIn("exec", columns)
            self.assertNotIn("path", columns)

    def test_automatic_sync_and_persistence(self) -> None:
        """Verify that game synchronization stores and enriches metadata."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "metadata.db"
            cache = MetadataCache(db_path=db_path)

            game = Game(
                id="steam_730",
                name="Counter-Strike 2",
                source="steam",
                launcher="steam",
                icon=Path("/tmp/cs2.png"),
                cover=Path("/tmp/cs2_cover.jpg"),
                favorite=False,
            )

            # Initial sync
            cache.sync_game(game)

            meta = cache.get_metadata("steam_730")
            self.assertIsNotNone(meta)
            self.assertEqual(meta.id, "steam_730")
            self.assertEqual(meta.icon, "/tmp/cs2.png")
            self.assertEqual(meta.cover, "/tmp/cs2_cover.jpg")
            self.assertEqual(meta.launch_count, 0)
            self.assertIsNone(meta.last_played)
            self.assertFalse(meta.favorite)

            # Update favorite in cache
            cache.set_favorite("steam_730", True)

            # Re-syncing a fresh Game instance should restore favorite
            game_fresh = Game(
                id="steam_730",
                name="Counter-Strike 2",
                source="steam",
                launcher="steam",
                favorite=False,
            )
            synced = cache.sync_game(game_fresh)
            self.assertTrue(synced.favorite)

    def test_record_launch_increments_and_timestamps(self) -> None:
        """Verify that record_launch increments count and updates last_played."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "metadata.db"
            cache = MetadataCache(db_path=db_path)

            game_id = "lutris_wukong"

            # Launch #1
            cache.record_launch(game_id)
            meta1 = cache.get_metadata(game_id)
            self.assertIsNotNone(meta1)
            self.assertEqual(meta1.launch_count, 1)
            self.assertIsNotNone(meta1.last_played)

            # Launch #2
            cache.record_launch(game_id)
            meta2 = cache.get_metadata(game_id)
            self.assertIsNotNone(meta2)
            self.assertEqual(meta2.launch_count, 2)


if __name__ == "__main__":
    unittest.main()
