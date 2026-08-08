"""Unit tests for Backup and Restore system (Favorites, Collections, Tags, Overrides, Artwork, SQLite data)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from gamedeck.backup import BackupData, BackupManager, export_backup, restore_backup
from gamedeck.collections import CollectionManager
from gamedeck.database import MetadataCache
from gamedeck.models import Game
from gamedeck.profiles import LaunchProfile, ProfileManager
from gamedeck.tags import TagManager


class TestBackupRestoreSystem(unittest.TestCase):
    """Test full JSON export and restore of GameDeck database and customizations."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_db = self.root / "source.db"
        self.target_db = self.root / "target.db"

        self.source_cache = MetadataCache(db_path=self.source_db)
        self.target_cache = MetadataCache(db_path=self.target_db)

        self.backup_mgr_source = BackupManager(metadata_cache=self.source_cache)
        self.backup_mgr_target = BackupManager(metadata_cache=self.target_cache)

        # Seed source state
        # 1. Favorite
        self.source_cache.toggle_favorite("steam_730")

        # 2. Collections
        col_mgr = CollectionManager(metadata_cache=self.source_cache)
        cid = col_mgr.create_custom_collection("Souls Collection", icon="⚔️", description="Challenging games")
        col_mgr.add_game_to_collection(cid, "lutris_bmw")

        # 3. Tags
        tag_mgr = TagManager(metadata_cache=self.source_cache)
        tag_mgr.add_tag_to_game("lutris_bmw", "Soulslike")
        tag_mgr.add_tag_to_game("lutris_bmw", "Action RPG")

        # 4. Overrides & Artwork references
        self.source_cache.update_game_properties(
            game_id="lutris_bmw",
            name="Black Myth: Wukong (Enhanced)",
            icon=Path("/tmp/custom_icon.png"),
            cover=Path("/tmp/custom_cover.jpg"),
        )

        # 5. Launch profiles
        prof_mgr = ProfileManager(metadata_cache=self.source_cache)
        prof_mgr.save_profile(
            LaunchProfile(
                id="bmw_ge_proton",
                game_id="lutris_bmw",
                name="GE-Proton8",
                launcher="proton",
                env_vars={"DXVK_ASYNC": "1"},
                is_default=True,
            )
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_export_backup_data_structure(self) -> None:
        """Verify export captures all categories (Favorites, Collections, Tags, Overrides, Profiles, Artwork)."""
        backup = self.backup_mgr_source.export_backup()

        self.assertIn("steam_730", backup.favorites)
        self.assertEqual(len(backup.collections), 1)
        self.assertEqual(backup.collections[0]["name"], "Souls Collection")
        self.assertEqual(len(backup.collection_items), 1)

        tag_names = {t["name"] for t in backup.tags}
        self.assertIn("Soulslike", tag_names)
        self.assertIn("Action RPG", tag_names)

        self.assertTrue(len(backup.launch_profiles) >= 1)
        self.assertTrue(len(backup.artwork_references) >= 1)

    def test_json_file_export_and_restore_cycle(self) -> None:
        """Verify writing JSON to disk and restoring into a clean target database."""
        json_file = self.root / "backup.json"
        self.backup_mgr_source.export_backup(output_file=json_file)
        self.assertTrue(json_file.is_file())

        # Target database starts clean
        self.assertEqual(len(self.target_cache.get_favorites()), 0)

        # Restore
        self.assertTrue(self.backup_mgr_target.restore_backup(json_file))

        # Verify favorites restored
        self.assertIn("steam_730", self.target_cache.get_favorites())

        # Verify collections restored
        dummy_games = [Game(id="lutris_bmw", name="BMW", source="lutris", launcher="lutris")]
        target_colls = CollectionManager(metadata_cache=self.target_cache).get_custom_collections(dummy_games)
        self.assertEqual(len(target_colls), 1)
        self.assertEqual(target_colls[0].name, "Souls Collection")
        self.assertEqual(target_colls[0].count(), 1)

        # Verify tags restored
        target_tags = TagManager(metadata_cache=self.target_cache).get_tags_for_game("lutris_bmw")
        self.assertIn("Soulslike", target_tags)

        # Verify launch profiles restored
        target_profs = ProfileManager(metadata_cache=self.target_cache).get_profiles(dummy_games[0])
        prof_names = {p.name for p in target_profs}
        self.assertIn("GE-Proton8", prof_names)


if __name__ == "__main__":
    unittest.main()
