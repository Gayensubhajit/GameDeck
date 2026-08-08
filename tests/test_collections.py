"""Unit tests for Dynamic Collections, Provider Groups, and SQLite custom collections."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gamedeck.collections import (
    CollectionManager,
    FavoritesCollectionGenerator,
    FilesystemCollectionGenerator,
    GameCollection,
    HeroicCollectionGenerator,
    InstalledCollectionGenerator,
    LutrisCollectionGenerator,
    NativeCollectionGenerator,
    RecentlyPlayedCollectionGenerator,
    SteamCollectionGenerator,
    get_all_collections,
)
from gamedeck.database import MetadataCache
from gamedeck.models import Game


class TestCollectionsSystem(unittest.TestCase):
    """Test dynamic collections generation and custom SQLite collections persistence."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.cache = MetadataCache(db_path=self.root / "metadata.db")
        self.manager = CollectionManager(metadata_cache=self.cache)

        # Sample test games across providers
        self.games = [
            Game(id="steam_730", name="CS2", source="steam", launcher="steam", favorite=True, installed=True, last_played="2026-08-08T12:00:00Z"),
            Game(id="lutris_bmw", name="Black Myth: Wukong", source="lutris", launcher="lutris", favorite=False, installed=True, last_played="2026-08-07T10:00:00Z"),
            Game(id="heroic_cyber", name="Cyberpunk 2077", source="heroic", launcher="heroic", favorite=True, installed=True),
            Game(id="native_kblocks", name="KBlocks", source="native", launcher="native", favorite=False, installed=True),
            Game(id="fs_game", name="Indie Game", source="filesystem", launcher="wine", favorite=False, installed=True),
        ]

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_favorites_collection(self) -> None:
        """Verify Favorites dynamic collection filters only favorited games."""
        gen = FavoritesCollectionGenerator()
        coll = gen.generate(self.games, self.cache)
        self.assertEqual(coll.name, "Favorites")
        self.assertEqual(coll.count(), 2)
        game_ids = {g.id for g in coll.games}
        self.assertIn("steam_730", game_ids)
        self.assertIn("heroic_cyber", game_ids)
        self.assertNotIn("lutris_bmw", game_ids)

    def test_recently_played_collection(self) -> None:
        """Verify Recently Played dynamic collection sorts by last_played timestamp."""
        gen = RecentlyPlayedCollectionGenerator()
        coll = gen.generate(self.games, self.cache)
        self.assertEqual(coll.name, "Recently Played")
        self.assertEqual(coll.count(), 2)
        # Most recent first
        self.assertEqual(coll.games[0].id, "steam_730")
        self.assertEqual(coll.games[1].id, "lutris_bmw")

    def test_installed_collection(self) -> None:
        """Verify Installed collection lists all currently installed games."""
        gen = InstalledCollectionGenerator()
        coll = gen.generate(self.games, self.cache)
        self.assertEqual(coll.count(), 5)

    def test_provider_collections(self) -> None:
        """Verify provider-specific collections (Steam, Lutris, Heroic, Native, Filesystem)."""
        steam_coll = SteamCollectionGenerator().generate(self.games, self.cache)
        self.assertEqual(steam_coll.count(), 1)
        self.assertEqual(steam_coll.games[0].id, "steam_730")

        lutris_coll = LutrisCollectionGenerator().generate(self.games, self.cache)
        self.assertEqual(lutris_coll.count(), 1)
        self.assertEqual(lutris_coll.games[0].id, "lutris_bmw")

        heroic_coll = HeroicCollectionGenerator().generate(self.games, self.cache)
        self.assertEqual(heroic_coll.count(), 1)
        self.assertEqual(heroic_coll.games[0].id, "heroic_cyber")

        native_coll = NativeCollectionGenerator().generate(self.games, self.cache)
        self.assertEqual(native_coll.count(), 1)
        self.assertEqual(native_coll.games[0].id, "native_kblocks")

        fs_coll = FilesystemCollectionGenerator().generate(self.games, self.cache)
        self.assertEqual(fs_coll.count(), 1)
        self.assertEqual(fs_coll.games[0].id, "fs_game")

    def test_custom_sqlite_collection_lifecycle(self) -> None:
        """Verify creating, adding games, querying, and deleting custom SQLite collections."""
        # 1. Create custom collection
        cid = self.manager.create_custom_collection(
            name="Action RPGs",
            icon="⚔️",
            description="My favorite action RPG titles",
        )
        self.assertEqual(cid, "action_rpgs")

        # 2. Add games
        self.assertTrue(self.manager.add_game_to_collection(cid, "lutris_bmw"))
        self.assertTrue(self.manager.add_game_to_collection(cid, "heroic_cyber"))

        # 3. Retrieve custom collections
        customs = self.manager.get_custom_collections(self.games)
        self.assertEqual(len(customs), 1)
        self.assertEqual(customs[0].name, "Action RPGs")
        self.assertEqual(customs[0].icon, "⚔️")
        self.assertEqual(customs[0].count(), 2)

        # 4. Remove a game
        self.assertTrue(self.manager.remove_game_from_collection(cid, "heroic_cyber"))
        customs2 = self.manager.get_custom_collections(self.games)
        self.assertEqual(customs2[0].count(), 1)

        # 5. Delete collection
        self.assertTrue(self.manager.delete_custom_collection(cid))
        customs_empty = self.manager.get_custom_collections(self.games)
        self.assertEqual(len(customs_empty), 0)

    def test_get_all_collections_helper(self) -> None:
        """Verify get_all_collections combines dynamic and custom lists."""
        cid = self.manager.create_custom_collection(name="Favorites 2", icon="⭐")
        self.manager.add_game_to_collection(cid, self.games[0].id)
        all_colls = self.manager.get_all_collections(self.games)
        names = {c.name for c in all_colls}
        self.assertIn("Favorites", names)
        self.assertIn("Recently Played", names)
        self.assertIn("Steam", names)
        self.assertIn("Lutris", names)
        self.assertIn("Favorites 2", names)


if __name__ == "__main__":
    unittest.main()
