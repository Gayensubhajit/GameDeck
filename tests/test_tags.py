"""Unit tests for the dynamic Game Tagging system, SQLite persistence, and search indexing."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gamedeck.database import MetadataCache
from gamedeck.models import Game
from gamedeck.search import SearchIndex
from gamedeck.tags import COMMON_TAGS, TagManager


class TestGameTagsSystem(unittest.TestCase):
    """Test tag assignment, persistence in SQLite, querying, and search integration."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.cache = MetadataCache(db_path=self.root / "metadata.db")
        self.tag_manager = TagManager(metadata_cache=self.cache)

        self.games = [
            Game(id="steam_1245620", name="Elden Ring", source="steam", launcher="steam"),
            Game(id="lutris_bmw", name="Black Myth: Wukong", source="lutris", launcher="lutris"),
            Game(id="steam_730", name="Counter-Strike 2", source="steam", launcher="steam"),
        ]

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_default_common_tags_seeded(self) -> None:
        """Verify common tags (RPG, Soulslike, FPS, Indie, Co-op, Finished, Wishlist) exist."""
        all_tags = self.tag_manager.get_all_tags()
        tag_names = {t.name for t in all_tags}
        for expected in ("RPG", "Soulslike", "FPS", "Indie", "Co-op", "Finished", "Wishlist"):
            self.assertIn(expected, tag_names)

    def test_assign_and_remove_tags(self) -> None:
        """Verify adding, querying, and removing tags on games."""
        # Add tags to Elden Ring
        self.assertTrue(self.tag_manager.add_tag_to_game("steam_1245620", "Soulslike"))
        self.assertTrue(self.tag_manager.add_tag_to_game("steam_1245620", "RPG"))

        tags = self.tag_manager.get_tags_for_game("steam_1245620")
        self.assertIn("Soulslike", tags)
        self.assertIn("RPG", tags)

        # Remove tag
        self.assertTrue(self.tag_manager.remove_tag_from_game("steam_1245620", "RPG"))
        tags_after = self.tag_manager.get_tags_for_game("steam_1245620")
        self.assertNotIn("RPG", tags_after)
        self.assertIn("Soulslike", tags_after)

    def test_tag_search_indexing(self) -> None:
        """Verify that games are searchable by their assigned tags in SearchIndex."""
        self.tag_manager.add_tag_to_game("steam_1245620", "Soulslike")
        self.tag_manager.add_tag_to_game("steam_1245620", "RPG")
        self.tag_manager.add_tag_to_game("lutris_bmw", "Soulslike")
        self.tag_manager.add_tag_to_game("steam_730", "FPS")
        self.tag_manager.add_tag_to_game("steam_730", "Co-op")

        tags_map = self.tag_manager.get_all_game_tags_map()
        index = SearchIndex.build(self.games, tags_map=tags_map)

        # Search for "Soulslike"
        results_soulslike = index.search("Soulslike")
        soulslike_ids = {r.game.id for r in results_soulslike}
        self.assertIn("steam_1245620", soulslike_ids)
        self.assertIn("lutris_bmw", soulslike_ids)
        self.assertNotIn("steam_730", soulslike_ids)

        # Search for "FPS"
        results_fps = index.search("FPS")
        fps_ids = {r.game.id for r in results_fps}
        self.assertIn("steam_730", fps_ids)
        self.assertNotIn("steam_1245620", fps_ids)

    def test_get_games_for_tag(self) -> None:
        """Verify filtering games by tag label."""
        self.tag_manager.add_tag_to_game("steam_1245620", "Wishlist")
        matches = self.tag_manager.get_games_for_tag("Wishlist", self.games)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].id, "steam_1245620")


if __name__ == "__main__":
    unittest.main()
