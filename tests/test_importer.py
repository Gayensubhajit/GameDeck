"""Unit tests for Library Category Importers (Steam, Lutris, Heroic) and duplicate prevention."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from gamedeck.collections import CollectionManager
from gamedeck.database import MetadataCache
from gamedeck.importer import (
    HeroicCategoryImporter,
    LibraryImporter,
    LutrisCategoryImporter,
    SteamCategoryImporter,
)
from gamedeck.models import Game


class TestLibraryCategoryImporter(unittest.TestCase):
    """Test importing categories from Steam, Lutris, and Heroic configurations."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.cache = MetadataCache(db_path=self.root / "metadata.db")
        self.collection_manager = CollectionManager(metadata_cache=self.cache)

        # Games fixture
        self.games = [
            Game(id="steam_730", name="Counter-Strike 2", source="steam", launcher="steam", appid="730"),
            Game(id="steam_1245620", name="Elden Ring", source="steam", launcher="steam", appid="1245620"),
            Game(id="lutris_bmw", name="Black Myth: Wukong", source="lutris", launcher="lutris", appid="bmw"),
            Game(id="heroic_cyber", name="Cyberpunk 2077", source="heroic", launcher="heroic", appid="cyberpunk"),
        ]

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_steam_vdf_and_json_category_import(self) -> None:
        """Verify importing Steam categories from local storage JSON without duplicates."""
        steam_root = self.root / "Steam"
        user_cloud = steam_root / "userdata" / "12345" / "config" / "cloudstorage"
        user_cloud.mkdir(parents=True)

        collections_json = user_cloud / "collections.json"
        collections_json.write_text(
            json.dumps([
                {"name": "Multiplayer Competitive", "added": ["730"]},
                {"name": "Masterpieces", "added": ["730", "1245620"]},
            ])
        )

        importer = SteamCategoryImporter(steam_roots=[steam_root])
        res = importer.import_categories(self.games, self.collection_manager)

        self.assertEqual(res.launcher, "steam")
        self.assertEqual(res.collections_created, 2)
        self.assertEqual(res.items_imported, 3)

        # Check collections exist in SQLite
        colls = self.collection_manager.get_custom_collections(self.games)
        names = {c.name for c in colls}
        self.assertIn("Multiplayer Competitive", names)
        self.assertIn("Masterpieces", names)

        # Manual refresh: Re-importing must not create duplicate items
        res2 = importer.import_categories(self.games, self.collection_manager)
        self.assertEqual(res2.items_imported, 0)

    def test_lutris_category_import_from_yaml(self) -> None:
        """Verify importing Lutris categories from game YAML files."""
        cfg_dir = self.root / "lutris" / "games"
        cfg_dir.mkdir(parents=True)

        bmw_yaml = cfg_dir / "bmw.yml"
        bmw_yaml.write_text(
            "name: 'Black Myth: Wukong'\n"
            "game_slug: bmw\n"
            "categories:\n"
            "  - Soulslike Action\n"
            "  - Finished 2026\n"
        )

        importer = LutrisCategoryImporter(config_dirs=[cfg_dir], db_paths=[])
        res = importer.import_categories(self.games, self.collection_manager)

        self.assertEqual(res.launcher, "lutris")
        self.assertEqual(res.collections_created, 2)
        self.assertEqual(res.items_imported, 2)

        colls = self.collection_manager.get_custom_collections(self.games)
        names = {c.name for c in colls}
        self.assertIn("Soulslike Action", names)
        self.assertIn("Finished 2026", names)

    def test_heroic_category_import(self) -> None:
        """Verify importing Heroic categories from store_cache/categories.json."""
        heroic_root = self.root / "heroic"
        store_cache = heroic_root / "store_cache"
        store_cache.mkdir(parents=True)

        cat_file = store_cache / "categories.json"
        cat_file.write_text(
            json.dumps({
                "Sci-Fi RPGs": ["cyberpunk"]
            })
        )

        importer = HeroicCategoryImporter(heroic_roots=[heroic_root])
        res = importer.import_categories(self.games, self.collection_manager)

        self.assertEqual(res.launcher, "heroic")
        self.assertEqual(res.collections_created, 1)
        self.assertEqual(res.items_imported, 1)

        colls = self.collection_manager.get_custom_collections(self.games)
        names = {c.name for c in colls}
        self.assertIn("Sci-Fi RPGs", names)

    def test_unified_library_importer_refresh(self) -> None:
        """Verify LibraryImporter coordinates all launcher category imports."""
        importer = LibraryImporter(metadata_cache=self.cache)
        results = importer.import_all(self.games)
        self.assertEqual(len(results), 3)


if __name__ == "__main__":
    unittest.main()
