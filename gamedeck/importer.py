"""Library Category Importer for Steam, Lutris, and Heroic launchers.

Parses launcher categories / tags / genre collections from their respective local
configuration files and imports them into GameDeck Collections without duplicates.
Supports manual re-importing / refreshing.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from gamedeck.collections import CollectionManager
from gamedeck.database import MetadataCache
from gamedeck.models import Game

__all__ = [
    "CategoryImportResult",
    "BaseCategoryImporter",
    "SteamCategoryImporter",
    "LutrisCategoryImporter",
    "HeroicCategoryImporter",
    "LibraryImporter",
]

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class CategoryImportResult:
    """Summary statistics for a launcher category import run.

    Attributes:
        launcher: Name of the launcher imported ('steam', 'lutris', 'heroic').
        collections_created: Number of new collections created.
        items_imported: Total number of game-to-collection assignments added.
        errors: List of any non-fatal parsing errors encountered.
    """

    launcher: str
    collections_created: int
    items_imported: int
    errors: list[str] = field(default_factory=list)


class BaseCategoryImporter:
    """Abstract base class for launcher category importers."""

    launcher_name: str

    def import_categories(
        self,
        all_games: list[Game],
        collection_manager: CollectionManager,
    ) -> CategoryImportResult:
        """Scan and import categories into GameDeck collections.

        Args:
            all_games: Currently available Game instances.
            collection_manager: Persistence manager.

        Returns:
            CategoryImportResult summary.
        """
        raise NotImplementedError


# -----------------------------------------------------------------------------
# Steam Category Importer
# -----------------------------------------------------------------------------


@dataclass(slots=True)
class SteamCategoryImporter(BaseCategoryImporter):
    """Imports Steam user categories from localuserdata / sharedconfig.vdf and cloud cache."""

    launcher_name: str = "steam"
    steam_roots: list[Path] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.steam_roots:
            home = Path.home()
            xdg_data = Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share"))
            candidates = [
                xdg_data / "Steam",
                home / ".steam" / "steam",
                home / ".steam" / "root",
                home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam",
                home / ".var" / "app" / "com.valvesoftware.Steam" / ".steam" / "steam",
            ]
            self.steam_roots = [c for c in candidates if c.is_dir()]

    def import_categories(
        self,
        all_games: list[Game],
        collection_manager: CollectionManager,
    ) -> CategoryImportResult:
        collections_created = 0
        items_imported = 0
        errors: list[str] = []

        steam_games = {g.appid: g.id for g in all_games if (g.source or "").lower() == "steam" and g.appid}
        if not steam_games:
            return CategoryImportResult(self.launcher_name, 0, 0)

        # Discovered mapping: category_name -> list of game_ids
        categories_map: dict[str, set[str]] = {}

        for root in self.steam_roots:
            userdata = root / "userdata"
            if not userdata.is_dir():
                continue

            for user_dir in userdata.iterdir():
                if not user_dir.is_dir() or not user_dir.name.isdigit():
                    continue

                # 1. Check sharedconfig.vdf (Legacy categories)
                shared_config = user_dir / "7" / "remote" / "sharedconfig.vdf"
                if shared_config.is_file():
                    try:
                        self._parse_vdf_categories(shared_config, steam_games, categories_map)
                    except Exception as err:
                        errors.append(f"Failed parsing {shared_config}: {err}")

                # 2. Check localstorage or collections in cloud storage
                cloud_colls = user_dir / "config" / "cloudstorage"
                if cloud_colls.is_dir():
                    for f in cloud_colls.glob("*.json"):
                        try:
                            self._parse_json_categories(f, steam_games, categories_map)
                        except Exception as err:
                            errors.append(f"Failed parsing {f}: {err}")

        # Import categories without duplicates
        for cat_name, gids in categories_map.items():
            if not cat_name.strip() or not gids:
                continue
            clean_name = cat_name.strip()
            clean_slug = clean_name.lower().replace(" ", "_").replace("-", "_")
            cid = f"steam_{clean_slug}"
            try:
                collection_manager.create_custom_collection(
                    name=clean_name,
                    icon="🌐",
                    description=f"Imported from Steam category '{clean_name}'",
                    collection_id=cid,
                )
                collections_created += 1
            except Exception:
                pass  # already exists

            for gid in gids:
                if collection_manager.add_game_to_collection(cid, gid):
                    items_imported += 1

        return CategoryImportResult(
            launcher=self.launcher_name,
            collections_created=collections_created,
            items_imported=items_imported,
            errors=errors,
        )

    def _parse_vdf_categories(
        self,
        vdf_path: Path,
        steam_games: dict[str, str],
        categories_map: dict[str, set[str]],
    ) -> None:
        """Parse key-value text in sharedconfig.vdf for categories."""
        content = vdf_path.read_text(encoding="utf-8", errors="replace")
        # Match pattern: "AppID" { "tags" { "0" "CategoryName" } }
        # Or "tags" { ... } blocks
        app_blocks = re.findall(r'"(\d+)"\s*\{([^}]+)\}', content)
        for appid, body in app_blocks:
            if appid in steam_games:
                gid = steam_games[appid]
                # Look for tags inside body
                tag_matches = re.findall(r'"tags"\s*\{([^}]+)\}', body)
                for tblock in tag_matches:
                    tags = re.findall(r'"\d+"\s*"([^"]+)"', tblock)
                    for t in tags:
                        categories_map.setdefault(t, set()).add(gid)

                # Look for single category fields
                single_cat = re.findall(r'"category"\s*"([^"]+)"', body, re.IGNORECASE)
                for c in single_cat:
                    categories_map.setdefault(c, set()).add(gid)

    def _parse_json_categories(
        self,
        json_path: Path,
        steam_games: dict[str, str],
        categories_map: dict[str, set[str]],
    ) -> None:
        """Parse modern Steam collections stored in JSON."""
        data = json.loads(json_path.read_text(encoding="utf-8", errors="replace"))
        if isinstance(data, list):
            for entry in data:
                if isinstance(entry, dict) and "name" in entry and "added" in entry:
                    name = entry.get("name")
                    added = entry.get("added", [])
                    if isinstance(name, str) and isinstance(added, list):
                        for appid_val in added:
                            appid_str = str(appid_val)
                            if appid_str in steam_games:
                                categories_map.setdefault(name, set()).add(steam_games[appid_str])


# -----------------------------------------------------------------------------
# Lutris Category Importer
# -----------------------------------------------------------------------------


@dataclass(slots=True)
class LutrisCategoryImporter(BaseCategoryImporter):
    """Imports categories and tags from Lutris SQLite database (pga.db) and yaml files."""

    launcher_name: str = "lutris"
    db_paths: list[Path] = field(default_factory=list)
    config_dirs: list[Path] = field(default_factory=list)

    def __post_init__(self) -> None:
        home = Path.home()
        if not self.db_paths:
            candidates = [
                home / ".local" / "share" / "lutris" / "pga.db",
                home / ".var" / "app" / "net.lutris.Lutris" / "data" / "lutris" / "pga.db",
            ]
            self.db_paths = [c for c in candidates if c.is_file()]

        if not self.config_dirs:
            cfg_candidates = [
                home / ".config" / "lutris" / "games",
                home / ".var" / "app" / "net.lutris.Lutris" / "config" / "lutris" / "games",
            ]
            self.config_dirs = [c for c in cfg_candidates if c.is_dir()]

    def import_categories(
        self,
        all_games: list[Game],
        collection_manager: CollectionManager,
    ) -> CategoryImportResult:
        collections_created = 0
        items_imported = 0
        errors: list[str] = []

        lutris_games = {
            (g.appid or g.id.removeprefix("lutris_")): g.id
            for g in all_games
            if (g.source or "").lower() == "lutris"
        }
        if not lutris_games:
            return CategoryImportResult(self.launcher_name, 0, 0)

        categories_map: dict[str, set[str]] = {}

        # 1. Query Lutris pga.db for categories table or categories field
        for db_path in self.db_paths:
            try:
                conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
                conn.row_factory = sqlite3.Row
                with conn:
                    # Check if categories table exists
                    table_cur = conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('categories', 'games_categories')"
                    )
                    tables = {row["name"] for row in table_cur.fetchall()}
                    if "categories" in tables and "games_categories" in tables:
                        cursor = conn.execute(
                            """
                            SELECT c.name as cat_name, g.slug as slug
                            FROM categories c
                            JOIN games_categories gc ON c.id = gc.category_id
                            JOIN games g ON gc.game_id = g.id
                            """
                        )
                        for row in cursor.fetchall():
                            cat = row["cat_name"]
                            slug = row["slug"]
                            if slug in lutris_games:
                                categories_map.setdefault(cat, set()).add(lutris_games[slug])
            except Exception as err:
                errors.append(f"Lutris SQLite pga.db read error: {err}")

        # 2. Check Lutris YAML files for categories field
        for cfg_dir in self.config_dirs:
            for yaml_file in cfg_dir.glob("*.yml"):
                try:
                    data = yaml.safe_load(yaml_file.read_text(encoding="utf-8", errors="replace"))
                    if isinstance(data, dict):
                        slug = yaml_file.stem
                        gid = lutris_games.get(slug)
                        if gid:
                            cats = data.get("categories") or []
                            if isinstance(cats, str):
                                cats = [cats]
                            if isinstance(cats, list):
                                for c in cats:
                                    if isinstance(c, str) and c.strip():
                                        categories_map.setdefault(c.strip(), set()).add(gid)
                except Exception as err:
                    errors.append(f"Error reading Lutris yaml '{yaml_file.name}': {err}")

        # Persist to collections
        for cat_name, gids in categories_map.items():
            clean_name = cat_name.strip()
            if not clean_name or not gids:
                continue
            clean_slug = clean_name.lower().replace(" ", "_").replace("-", "_")
            cid = f"lutris_{clean_slug}"
            try:
                collection_manager.create_custom_collection(
                    name=clean_name,
                    icon="🍷",
                    description=f"Imported from Lutris category '{clean_name}'",
                    collection_id=cid,
                )
                collections_created += 1
            except Exception:
                pass

            for gid in gids:
                if collection_manager.add_game_to_collection(cid, gid):
                    items_imported += 1

        return CategoryImportResult(
            launcher=self.launcher_name,
            collections_created=collections_created,
            items_imported=items_imported,
            errors=errors,
        )


# -----------------------------------------------------------------------------
# Heroic Category Importer
# -----------------------------------------------------------------------------


@dataclass(slots=True)
class HeroicCategoryImporter(BaseCategoryImporter):
    """Imports user categories and tags from Heroic Games Launcher configuration."""

    launcher_name: str = "heroic"
    heroic_roots: list[Path] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.heroic_roots:
            home = Path.home()
            xdg_config = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
            candidates = [
                xdg_config / "heroic",
                home / ".config" / "heroic",
                home / ".var" / "app" / "com.heroicgameslauncher.hgl" / "config" / "heroic",
            ]
            self.heroic_roots = [c for c in candidates if c.is_dir()]

    def import_categories(
        self,
        all_games: list[Game],
        collection_manager: CollectionManager,
    ) -> CategoryImportResult:
        collections_created = 0
        items_imported = 0
        errors: list[str] = []

        heroic_games = {
            (g.appid or g.id.removeprefix("heroic_")): g.id
            for g in all_games
            if (g.source or "").lower() == "heroic"
        }
        if not heroic_games:
            return CategoryImportResult(self.launcher_name, 0, 0)

        categories_map: dict[str, set[str]] = {}

        for root in self.heroic_roots:
            # 1. Check store_cache / categories / tags
            cat_files = [
                root / "store_cache" / "categories.json",
                root / "store_cache" / "custom_categories.json",
                root / "categories.json",
            ]
            for f in cat_files:
                if f.is_file():
                    try:
                        data = json.loads(f.read_text(encoding="utf-8", errors="replace"))
                        # Structure: { "CategoryName": ["app_name1", "app_name2"] } or list of objs
                        if isinstance(data, dict):
                            for cat_name, app_list in data.items():
                                if isinstance(app_list, list):
                                    for app in app_list:
                                        app_str = str(app)
                                        if app_str in heroic_games:
                                            categories_map.setdefault(cat_name, set()).add(
                                                heroic_games[app_str]
                                            )
                        elif isinstance(data, list):
                            for entry in data:
                                if isinstance(entry, dict):
                                    name = entry.get("name") or entry.get("category")
                                    apps = entry.get("apps") or entry.get("games") or []
                                    if name and isinstance(apps, list):
                                        for app in apps:
                                            app_str = str(app)
                                            if app_str in heroic_games:
                                                categories_map.setdefault(name, set()).add(
                                                    heroic_games[app_str]
                                                )
                    except Exception as err:
                        errors.append(f"Error parsing Heroic category file '{f}': {err}")

            # 2. Check individual game config overrides
            g_cfg_dir = root / "GamesConfig"
            if g_cfg_dir.is_dir():
                for cfg_file in g_cfg_dir.glob("*.json"):
                    try:
                        gdata = json.loads(cfg_file.read_text(encoding="utf-8", errors="replace"))
                        app_name = cfg_file.stem
                        gid = heroic_games.get(app_name)
                        if gid and isinstance(gdata, dict):
                            cats = gdata.get("categories") or gdata.get("tags") or []
                            if isinstance(cats, str):
                                cats = [cats]
                            if isinstance(cats, list):
                                for c in cats:
                                    if isinstance(c, str) and c.strip():
                                        categories_map.setdefault(c.strip(), set()).add(gid)
                    except Exception as err:
                        errors.append(f"Error reading game config '{cfg_file.name}': {err}")

        # Persist to collections
        for cat_name, gids in categories_map.items():
            clean_name = cat_name.strip()
            if not clean_name or not gids:
                continue
            clean_slug = clean_name.lower().replace(" ", "_").replace("-", "_")
            cid = f"heroic_{clean_slug}"
            try:
                collection_manager.create_custom_collection(
                    name=clean_name,
                    icon="🦸",
                    description=f"Imported from Heroic category '{clean_name}'",
                    collection_id=cid,
                )
                collections_created += 1
            except Exception:
                pass

            for gid in gids:
                if collection_manager.add_game_to_collection(cid, gid):
                    items_imported += 1

        return CategoryImportResult(
            launcher=self.launcher_name,
            collections_created=collections_created,
            items_imported=items_imported,
            errors=errors,
        )


# -----------------------------------------------------------------------------
# Unified Library Importer Coordinator
# -----------------------------------------------------------------------------


@dataclass(slots=True)
class LibraryImporter:
    """Coordinates category imports across Steam, Lutris, and Heroic launchers."""

    metadata_cache: MetadataCache = field(default_factory=MetadataCache)
    importers: list[BaseCategoryImporter] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.importers:
            self.importers = [
                SteamCategoryImporter(),
                LutrisCategoryImporter(),
                HeroicCategoryImporter(),
            ]

    def import_all(self, all_games: list[Game]) -> list[CategoryImportResult]:
        """Perform category discovery and import across all supported launchers.

        Avoids duplicate entries and preserves existing user collections.

        Args:
            all_games: List of discovered Game instances.

        Returns:
            List of CategoryImportResult summaries.
        """
        coll_manager = CollectionManager(metadata_cache=self.metadata_cache)
        results: list[CategoryImportResult] = []

        for imp in self.importers:
            try:
                res = imp.import_categories(all_games, coll_manager)
                results.append(res)
                logger.info(
                    "Imported from %s: %d collections, %d items",
                    res.launcher,
                    res.collections_created,
                    res.items_imported,
                )
            except Exception as err:
                logger.error("Category importer failed for '%s': %s", imp.launcher_name, err)
                results.append(
                    CategoryImportResult(
                        launcher=imp.launcher_name,
                        collections_created=0,
                        items_imported=0,
                        errors=[str(err)],
                    )
                )

        return results
