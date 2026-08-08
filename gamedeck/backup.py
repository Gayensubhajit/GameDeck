"""Comprehensive Backup and Restore system for GameDeck.

Exports and restores all local library customizations, preferences, and state to/from JSON:
- Favorites
- Custom Collections & item memberships
- Tags & game tag assignments
- Game Property Overrides (title, executable, launcher)
- Artwork references (icon, cover, logo, hero)
- Recent play history & launch statistics
- SQLite raw database tables
- Settings & configuration state
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gamedeck.config import Settings, load_settings
from gamedeck.database import MetadataCache

__all__ = [
    "BackupData",
    "BackupManager",
    "export_backup",
    "restore_backup",
]

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class BackupData:
    """Encapsulates the complete exported state of GameDeck."""

    version: int = 1
    exported_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    favorites: list[str] = field(default_factory=list)
    recent_history: list[dict[str, Any]] = field(default_factory=list)
    collections: list[dict[str, Any]] = field(default_factory=list)
    collection_items: list[dict[str, Any]] = field(default_factory=list)
    tags: list[dict[str, Any]] = field(default_factory=list)
    game_tags: list[dict[str, Any]] = field(default_factory=list)
    overrides: list[dict[str, Any]] = field(default_factory=list)
    artwork_references: list[dict[str, Any]] = field(default_factory=list)
    launch_profiles: list[dict[str, Any]] = field(default_factory=list)
    sqlite_dump: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    settings: dict[str, Any] = field(default_factory=dict)

    def to_json(self, indent: int = 2) -> str:
        """Serialize backup data to a JSON string."""
        return json.dumps(asdict(self), indent=indent, ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> BackupData:
        """Parse backup data from a JSON string."""
        data = json.loads(json_str)
        return cls(
            version=data.get("version", 1),
            exported_at=data.get("exported_at", ""),
            favorites=data.get("favorites", []),
            recent_history=data.get("recent_history", []),
            collections=data.get("collections", []),
            collection_items=data.get("collection_items", []),
            tags=data.get("tags", []),
            game_tags=data.get("game_tags", []),
            overrides=data.get("overrides", []),
            artwork_references=data.get("artwork_references", []),
            launch_profiles=data.get("launch_profiles", []),
            sqlite_dump=data.get("sqlite_dump", {}),
            settings=data.get("settings", {}),
        )

    def summary(self) -> str:
        """Return a concise one-line human-readable description of this backup.

        Useful for log messages and CLI output.

        Example::

            BackupData v1 (2026-08-08T09:31:57Z): 3 favorites, 2 collections,
            5 tags, 1 profiles, 4 artwork refs
        """
        return (
            f"BackupData v{self.version} ({self.exported_at}): "
            f"{len(self.favorites)} favorites, "
            f"{len(self.collections)} collections, "
            f"{len(self.tags)} tags, "
            f"{len(self.launch_profiles)} profiles, "
            f"{len(self.artwork_references)} artwork refs"
        )


@dataclass(slots=True)
class BackupManager:
    """Coordinates JSON export and restore for all GameDeck state."""

    metadata_cache: MetadataCache = field(default_factory=MetadataCache)

    def export_backup(self, output_file: Path | str | None = None) -> BackupData:
        """Export all GameDeck SQLite tables, customizations, and settings to BackupData.

        Args:
            output_file: Optional file path to save JSON output directly.

        Returns:
            Populated BackupData instance.
        """
        now = datetime.now(timezone.utc).isoformat()
        backup = BackupData(version=1, exported_at=now)

        with self.metadata_cache._get_connection() as conn:
            # 1. Favorites
            cur = conn.execute("SELECT id FROM game_metadata WHERE favorite = 1")
            backup.favorites = [r["id"] for r in cur.fetchall()]

            # 2. Recent play history
            cur = conn.execute(
                "SELECT id, last_played, launch_count FROM game_metadata WHERE last_played IS NOT NULL ORDER BY last_played DESC"
            )
            backup.recent_history = [
                {"id": r["id"], "last_played": r["last_played"], "launch_count": r["launch_count"]}
                for r in cur.fetchall()
            ]

            # 3. Custom collections
            cur = conn.execute("SELECT id, name, icon, description, created_at FROM custom_collections")
            backup.collections = [
                {"id": r["id"], "name": r["name"], "icon": r["icon"], "description": r["description"], "created_at": r["created_at"]}
                for r in cur.fetchall()
            ]

            # 4. Collection items
            cur = conn.execute("SELECT collection_id, game_id, added_at FROM collection_items")
            backup.collection_items = [
                {"collection_id": r["collection_id"], "game_id": r["game_id"], "added_at": r["added_at"]}
                for r in cur.fetchall()
            ]

            # 5. Tags & Game Tags
            cur = conn.execute("SELECT slug, name, created_at FROM tags")
            backup.tags = [{"slug": r["slug"], "name": r["name"], "created_at": r["created_at"]} for r in cur.fetchall()]

            cur = conn.execute("SELECT game_id, tag_slug, tagged_at FROM game_tags")
            backup.game_tags = [{"game_id": r["game_id"], "tag_slug": r["tag_slug"], "tagged_at": r["tagged_at"]} for r in cur.fetchall()]

            # 6. Artwork references — merged from both cached_games and game_metadata
            artwork_by_id: dict[str, dict] = {}
            cur = conn.execute("SELECT id, icon, logo, hero, cover, updated_at FROM cached_games")
            for r in cur.fetchall():
                if any([r["icon"], r["logo"], r["hero"], r["cover"]]):
                    artwork_by_id[r["id"]] = {
                        "id": r["id"],
                        "icon": r["icon"],
                        "logo": r["logo"],
                        "hero": r["hero"],
                        "cover": r["cover"],
                        "updated_at": r["updated_at"],
                    }
            cur = conn.execute("SELECT id, icon, logo, hero, cover, updated_at FROM game_metadata")
            for r in cur.fetchall():
                if any([r["icon"], r["logo"], r["hero"], r["cover"]]):
                    # Prefer cached_games data; merge missing fields from game_metadata
                    if r["id"] not in artwork_by_id:
                        artwork_by_id[r["id"]] = {
                            "id": r["id"],
                            "icon": r["icon"],
                            "logo": r["logo"],
                            "hero": r["hero"],
                            "cover": r["cover"],
                            "updated_at": r["updated_at"],
                        }
                    else:
                        existing = artwork_by_id[r["id"]]
                        existing["icon"] = existing["icon"] or r["icon"]
                        existing["logo"] = existing["logo"] or r["logo"]
                        existing["hero"] = existing["hero"] or r["hero"]
                        existing["cover"] = existing["cover"] or r["cover"]
            backup.artwork_references = list(artwork_by_id.values())

            # 7. Overrides & cached games
            cur = conn.execute("SELECT id, name, source, launcher, executable, icon, cover, logo, hero, installed, favorite, appid, last_played, launch_count FROM cached_games")
            backup.overrides = [dict(r) for r in cur.fetchall()]

            # 8. Launch Profiles
            cur = conn.execute("SELECT id, game_id, name, launcher, executable, launch_args, env_vars, is_default, created_at FROM launch_profiles")
            backup.launch_profiles = [dict(r) for r in cur.fetchall()]

            # 9. Complete SQLite dump dictionary
            tables = [
                "schema_migrations",
                "game_metadata",
                "cached_games",
                "custom_collections",
                "collection_items",
                "tags",
                "game_tags",
                "launch_profiles",
            ]
            for t in tables:
                try:
                    t_cur = conn.execute(f"SELECT * FROM {t}")
                    backup.sqlite_dump[t] = [dict(r) for r in t_cur.fetchall()]
                except Exception:
                    pass

        # 10. Settings snapshot
        try:
            settings_obj = load_settings()
            backup.settings = {
                "steam": settings_obj.providers.steam,
                "lutris": settings_obj.providers.lutris,
                "heroic": settings_obj.providers.heroic,
                "native": settings_obj.providers.native,
                "filesystem": settings_obj.providers.filesystem,
                "recent_limit": settings_obj.ui.recent_games_limit,
                "show_icons": settings_obj.ui.show_icons,
            }
        except Exception as err:
            logger.debug("Settings snapshot skipped: %s", err)

        if output_file:
            path = Path(output_file)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(backup.to_json(), encoding="utf-8")
            logger.info("Backup successfully written to '%s'", path)

        return backup

    def restore_backup(self, backup_input: BackupData | Path | str) -> bool:
        """Restore GameDeck SQLite database and state from a BackupData instance or JSON file.

        Args:
            backup_input: BackupData object or Path/string pointing to backup JSON file.

        Returns:
            True if restored successfully.
        """
        # Ensure all tables exist in target database
        from gamedeck.collections import CollectionManager
        from gamedeck.tags import TagManager
        from gamedeck.profiles import ProfileManager

        CollectionManager(metadata_cache=self.metadata_cache)
        TagManager(metadata_cache=self.metadata_cache)
        ProfileManager(metadata_cache=self.metadata_cache)

        # Load backup from file or accept BackupData directly
        if isinstance(backup_input, (Path, str)):
            path = Path(backup_input)
            if not path.is_file():
                raise FileNotFoundError(
                    f"Backup file not found: '{path}'. "
                    "Ensure the path is correct and the file exists before restoring."
                )
            try:
                backup = BackupData.from_json(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, KeyError, TypeError) as err:
                logger.error("Failed to parse backup file '%s': %s", path, err)
                return False
        else:
            backup = backup_input

        now = datetime.now(timezone.utc).isoformat()

        with self.metadata_cache._get_connection() as conn:
            # 1. Restore Custom Collections
            for c in backup.collections:
                conn.execute(
                    """
                    INSERT INTO custom_collections (id, name, icon, description, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        name = excluded.name,
                        icon = excluded.icon,
                        description = excluded.description
                    """,
                    (c["id"], c["name"], c.get("icon", "📁"), c.get("description", ""), c.get("created_at", now)),
                )

            # 2. Restore Collection Items
            for item in backup.collection_items:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO collection_items (collection_id, game_id, added_at)
                    VALUES (?, ?, ?)
                    """,
                    (item["collection_id"], item["game_id"], item.get("added_at", now)),
                )

            # 3. Restore Tags
            for t in backup.tags:
                conn.execute(
                    """
                    INSERT INTO tags (slug, name, created_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(slug) DO UPDATE SET name = excluded.name
                    """,
                    (t["slug"], t["name"], t.get("created_at", now)),
                )

            # 4. Restore Game Tags
            for gt in backup.game_tags:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO game_tags (game_id, tag_slug, tagged_at)
                    VALUES (?, ?, ?)
                    """,
                    (gt["game_id"], gt["tag_slug"], gt.get("tagged_at", now)),
                )

            # 5. Restore Artwork & Metadata references
            for art in backup.artwork_references:
                conn.execute(
                    """
                    INSERT INTO game_metadata (id, icon, logo, hero, cover, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        icon = COALESCE(excluded.icon, game_metadata.icon),
                        logo = COALESCE(excluded.logo, game_metadata.logo),
                        hero = COALESCE(excluded.hero, game_metadata.hero),
                        cover = COALESCE(excluded.cover, game_metadata.cover),
                        updated_at = excluded.updated_at
                    """,
                    (art["id"], art.get("icon"), art.get("logo"), art.get("hero"), art.get("cover"), art.get("updated_at", now)),
                )

            # 6. Restore Favorites
            for fav_id in backup.favorites:
                conn.execute(
                    """
                    INSERT INTO game_metadata (id, favorite, updated_at)
                    VALUES (?, 1, ?)
                    ON CONFLICT(id) DO UPDATE SET favorite = 1, updated_at = excluded.updated_at
                    """,
                    (fav_id, now),
                )
                conn.execute("UPDATE cached_games SET favorite = 1 WHERE id = ?", (fav_id,))

            # 7. Restore Recent history & launch counts
            for r in backup.recent_history:
                conn.execute(
                    """
                    INSERT INTO game_metadata (id, last_played, launch_count, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        last_played = excluded.last_played,
                        launch_count = excluded.launch_count,
                        updated_at = excluded.updated_at
                    """,
                    (r["id"], r.get("last_played"), r.get("launch_count", 0), now),
                )
                conn.execute(
                    "UPDATE cached_games SET last_played = ?, launch_count = ? WHERE id = ?",
                    (r.get("last_played"), r.get("launch_count", 0), r["id"]),
                )

            # 8. Restore Launch Profiles
            for prof in backup.launch_profiles:
                conn.execute(
                    """
                    INSERT INTO launch_profiles (id, game_id, name, launcher, executable, launch_args, env_vars, is_default, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        name = excluded.name,
                        launcher = excluded.launcher,
                        executable = excluded.executable,
                        launch_args = excluded.launch_args,
                        env_vars = excluded.env_vars,
                        is_default = excluded.is_default
                    """,
                    (
                        prof["id"],
                        prof["game_id"],
                        prof["name"],
                        prof["launcher"],
                        prof.get("executable"),
                        prof.get("launch_args", ""),
                        prof.get("env_vars", ""),
                        prof.get("is_default", 0),
                        prof.get("created_at", now),
                    ),
                )

            # 9. Restore cached games overrides
            for cg in backup.overrides:
                conn.execute(
                    """
                    INSERT INTO cached_games (id, name, source, launcher, executable, icon, cover, logo, hero, installed, favorite, appid, last_played, launch_count, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        name = excluded.name,
                        launcher = excluded.launcher,
                        executable = excluded.executable,
                        icon = COALESCE(excluded.icon, cached_games.icon),
                        cover = COALESCE(excluded.cover, cached_games.cover),
                        logo = COALESCE(excluded.logo, cached_games.logo),
                        hero = COALESCE(excluded.hero, cached_games.hero),
                        favorite = excluded.favorite,
                        last_played = COALESCE(excluded.last_played, cached_games.last_played),
                        launch_count = excluded.launch_count,
                        updated_at = excluded.updated_at
                    """,
                    (
                        cg["id"],
                        cg["name"],
                        cg.get("source", "native"),
                        cg.get("launcher", "native"),
                        cg.get("executable"),
                        cg.get("icon"),
                        cg.get("cover"),
                        cg.get("logo"),
                        cg.get("hero"),
                        cg.get("installed", 1),
                        cg.get("favorite", 0),
                        cg.get("appid"),
                        cg.get("last_played"),
                        cg.get("launch_count", 0),
                        now,
                    ),
                )

        logger.info("Successfully restored %s", backup.summary())
        return True


def export_backup(output_file: Path | str | None = None, metadata_cache: MetadataCache | None = None) -> BackupData:
    """Convenience helper to export GameDeck state to BackupData or JSON file."""
    mgr = BackupManager(metadata_cache=metadata_cache or MetadataCache())
    return mgr.export_backup(output_file)


def restore_backup(backup_input: BackupData | Path | str, metadata_cache: MetadataCache | None = None) -> bool:
    """Convenience helper to restore GameDeck state from BackupData or JSON file."""
    mgr = BackupManager(metadata_cache=metadata_cache or MetadataCache())
    return mgr.restore_backup(backup_input)
