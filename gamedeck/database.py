"""Unified SQLite library and metadata cache with incremental provider change detection."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator

from gamedeck.models import Game

__all__ = [
    "GameMetadata",
    "CachedGame",
    "MetadataCache",
    "LibraryCache",
    "get_default_db_path",
]

logger = logging.getLogger(__name__)


def get_default_db_path() -> Path:
    """Return standard path to the GameDeck SQLite database file (~/.local/share/gamedeck/metadata.db)."""
    home = Path.home()
    xdg_data = Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share"))
    return xdg_data / "gamedeck" / "metadata.db"


@dataclass(slots=True)
class GameMetadata:
    """Cached game metadata record."""

    id: str
    icon: str | None = None
    logo: str | None = None
    hero: str | None = None
    cover: str | None = None
    last_played: str | None = None
    launch_count: int = 0
    favorite: bool = False
    date_added: str | None = None
    version: str | None = None
    notes: str | None = None
    hidden: bool = False
    platform: str | None = None
    wine_version: str | None = None
    playtime_minutes: int = 0
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass(slots=True)
class CachedGame:
    """Snapshot of a cached game in the library cache."""

    id: str
    name: str
    source: str
    launcher: str
    executable: str | None = None
    icon: str | None = None
    logo: str | None = None
    hero: str | None = None
    cover: str | None = None
    installed: bool = True
    favorite: bool = False
    appid: str | None = None
    last_played: str | None = None
    launch_count: int = 0
    date_added: str | None = None
    version: str | None = None
    notes: str | None = None
    hidden: bool = False
    platform: str | None = None
    wine_version: str | None = None
    playtime_minutes: int = 0


@dataclass(slots=True)
class MetadataCache:
    """SQLite-backed library and metadata cache with provider change detection and migrations.

    Attributes:
        db_path: Path to the SQLite database file.
    """

    db_path: Path = field(default_factory=get_default_db_path)

    def __post_init__(self) -> None:
        """Initialize database directory, run migrations, and verify schema."""
        self._init_db()

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager yielding an open SQLite connection with WAL mode."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=10.0,
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            yield conn
            conn.commit()
        except Exception as err:
            conn.rollback()
            logger.error("Database operation failed on '%s': %s", self.db_path, err)
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        """Create database tables, run migrations, and ensure indices."""
        with self._get_connection() as conn:
            # 1. Schema versioning / migrations table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
                """
            )

            # 2. Base game_metadata table (backward-compatible)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS game_metadata (
                    id TEXT PRIMARY KEY,
                    icon TEXT,
                    logo TEXT,
                    hero TEXT,
                    cover TEXT,
                    last_played TEXT,
                    launch_count INTEGER NOT NULL DEFAULT 0,
                    favorite INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                )
                """
            )

            # 3. Cached games table for incremental scanning
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cached_games (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    source TEXT NOT NULL,
                    launcher TEXT NOT NULL,
                    executable TEXT,
                    icon TEXT,
                    logo TEXT,
                    hero TEXT,
                    cover TEXT,
                    installed INTEGER NOT NULL DEFAULT 1,
                    favorite INTEGER NOT NULL DEFAULT 0,
                    appid TEXT,
                    last_played TEXT,
                    launch_count INTEGER NOT NULL DEFAULT 0,
                    provider_fingerprint TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )

            # 4. Provider fingerprints table for detecting provider source changes
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS provider_fingerprints (
                    provider_name TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    scanned_at TEXT NOT NULL
                )
                """
            )

            # Run migrations
            self._run_migrations(conn)

            # Indices
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_game_metadata_favorite ON game_metadata(favorite)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_game_metadata_last_played ON game_metadata(last_played)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_cached_games_source ON cached_games(source)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_cached_games_favorite ON cached_games(favorite)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_cached_games_last_played ON cached_games(last_played)"
            )

    def _run_migrations(self, conn: sqlite3.Connection) -> None:
        """Apply database migrations sequentially."""
        cursor = conn.execute("SELECT version FROM schema_migrations ORDER BY version")
        applied_versions = {row["version"] for row in cursor.fetchall()}

        # Migration 1: Ensure logo & hero columns in game_metadata
        if 1 not in applied_versions:
            col_cursor = conn.execute("PRAGMA table_info(game_metadata)")
            existing_cols = {row["name"] for row in col_cursor.fetchall()}
            if "logo" not in existing_cols:
                conn.execute("ALTER TABLE game_metadata ADD COLUMN logo TEXT")
            if "hero" not in existing_cols:
                conn.execute("ALTER TABLE game_metadata ADD COLUMN hero TEXT")
            conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (1, ?)",
                (datetime.now(timezone.utc).isoformat(),),
            )

        # Migration 2: Ensure cached_games table has all needed fields
        if 2 not in applied_versions:
            col_cursor = conn.execute("PRAGMA table_info(cached_games)")
            cached_cols = {row["name"] for row in col_cursor.fetchall()}
            if "provider_fingerprint" not in cached_cols:
                conn.execute("ALTER TABLE cached_games ADD COLUMN provider_fingerprint TEXT")
            conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (2, ?)",
                (datetime.now(timezone.utc).isoformat(),),
            )

        # Migration 3: Ensure launch_profiles table exists
        # Previously created lazily by ProfileManager; moved here so backup restore
        # always works against a fresh database without requiring ProfileManager init.
        if 3 not in applied_versions:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS launch_profiles (
                    id TEXT PRIMARY KEY,
                    game_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    launcher TEXT NOT NULL,
                    executable TEXT,
                    launch_args TEXT DEFAULT '',
                    env_vars TEXT DEFAULT '',
                    is_default INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_launch_profiles_game ON launch_profiles(game_id)"
            )
            conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (3, ?)",
                (datetime.now(timezone.utc).isoformat(),),
            )

        # Migration 4: Purge internal test/tool apps (e.g. steam_888 / Enabled Game) from cached_games and game_metadata
        if 4 not in applied_versions:
            conn.execute("DELETE FROM cached_games WHERE appid = '888' OR id = 'steam_888' OR lower(name) = 'enabled game'")
            conn.execute("DELETE FROM game_metadata WHERE id = 'steam_888'")
            conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (4, ?)",
                (datetime.now(timezone.utc).isoformat(),),
            )

        # Migration 5: Add date_added, version, notes, hidden, platform, wine_version, playtime_minutes
        if 5 not in applied_versions:
            for table in ("game_metadata", "cached_games"):
                col_cursor = conn.execute(f"PRAGMA table_info({table})")
                existing_cols = {row["name"] for row in col_cursor.fetchall()}
                if "date_added" not in existing_cols:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN date_added TEXT")
                if "version" not in existing_cols:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN version TEXT")
                if "notes" not in existing_cols:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN notes TEXT")
                if "hidden" not in existing_cols:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0")
                if "platform" not in existing_cols:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN platform TEXT")
                if "wine_version" not in existing_cols:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN wine_version TEXT")
                if "playtime_minutes" not in existing_cols:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN playtime_minutes INTEGER NOT NULL DEFAULT 0")

            conn.execute("CREATE INDEX IF NOT EXISTS idx_cached_games_date_added ON cached_games(date_added)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cached_games_hidden ON cached_games(hidden)")
            conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (5, ?)",
                (datetime.now(timezone.utc).isoformat(),),
            )

        # Migration 6: game_sessions, save_backups, plugin_configs, and launch_profiles advanced fields
        if 6 not in applied_versions:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS game_sessions (
                    id TEXT PRIMARY KEY,
                    game_id TEXT NOT NULL,
                    start_time TEXT NOT NULL,
                    end_time TEXT,
                    duration_seconds INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_game_sessions_game ON game_sessions(game_id)")

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS save_backups (
                    id TEXT PRIMARY KEY,
                    game_id TEXT NOT NULL,
                    archive_path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    notes TEXT DEFAULT ''
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_save_backups_game ON save_backups(game_id)")

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS plugin_configs (
                    plugin_name TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    config_json TEXT DEFAULT '{}',
                    updated_at TEXT NOT NULL
                )
                """
            )

            # Ensure launch_profiles table has wrapper columns
            prof_cols = {row["name"] for row in conn.execute("PRAGMA table_info(launch_profiles)").fetchall()}
            for col, col_type in [
                ("use_gamemode", "INTEGER NOT NULL DEFAULT 0"),
                ("use_gamescope", "INTEGER NOT NULL DEFAULT 0"),
                ("use_mangohud", "INTEGER NOT NULL DEFAULT 0"),
                ("use_obs_vkcapture", "INTEGER NOT NULL DEFAULT 0"),
                ("pre_launch_script", "TEXT DEFAULT ''"),
                ("post_exit_script", "TEXT DEFAULT ''"),
            ]:
                if col not in prof_cols:
                    conn.execute(f"ALTER TABLE launch_profiles ADD COLUMN {col} {col_type}")

            conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (6, ?)",
                (datetime.now(timezone.utc).isoformat(),),
            )

    # ------------------------------------------------------------------
    # Incremental Provider Change Detection & Library Cache
    # ------------------------------------------------------------------

    def compute_provider_fingerprint(self, provider_name: str, scan_roots: list[Path] | None = None) -> str:
        """Compute a hash fingerprint representing the modification state of a provider's sources.

        For filesystem-type providers whose scan roots may be on NTFS-mounted partitions
        (where parent directory mtime is unreliable), this method enumerates immediate
        subdirectory names so that newly added game folders are detected.

        Args:
            provider_name: Provider name (e.g. steam, lutris, heroic, native, filesystem).
            scan_roots: Optional list of directories to hash stat timestamps for.

        Returns:
            SHA256 hex digest string.
        """
        hasher = hashlib.sha256()
        hasher.update(provider_name.encode("utf-8"))

        if scan_roots:
            for root in sorted(scan_roots, key=lambda p: str(p)):
                if root.exists():
                    try:
                        stat = root.stat()
                        hasher.update(f"{root}:{stat.st_mtime_ns}:{stat.st_size}".encode("utf-8"))
                        # Hash immediate children (manifest/yaml/desktop files or game folders)
                        if root.is_dir():
                            children = sorted(root.iterdir(), key=lambda p: p.name)[:100]
                            for child in children:
                                try:
                                    cstat = child.stat()
                                    # Include name, size, and mtime for detection on any filesystem
                                    hasher.update(
                                        f"{child.name}:{child.is_dir()}:{cstat.st_mtime_ns}:{cstat.st_size}".encode("utf-8")
                                    )
                                except OSError:
                                    pass
                    except OSError:
                        pass
        return hasher.hexdigest()

    def get_provider_fingerprint(self, provider_name: str) -> str | None:
        """Get the stored fingerprint for a provider from the last scan."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT fingerprint FROM provider_fingerprints WHERE provider_name = ?",
                (provider_name.lower().strip(),),
            )
            row = cursor.fetchone()
            return row["fingerprint"] if row else None

    def set_provider_fingerprint(self, provider_name: str, fingerprint: str) -> None:
        """Save a new fingerprint for a provider after scanning."""
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO provider_fingerprints (provider_name, fingerprint, scanned_at)
                VALUES (?, ?, ?)
                ON CONFLICT(provider_name) DO UPDATE SET fingerprint = excluded.fingerprint, scanned_at = excluded.scanned_at
                """,
                (provider_name.lower().strip(), fingerprint, now),
            )

    def is_provider_modified(self, provider_name: str, current_fingerprint: str) -> bool:
        """Return True if the provider has never been scanned or has changed since last scan."""
        stored = self.get_provider_fingerprint(provider_name)
        if stored is None:
            return True
        return stored != current_fingerprint

    def get_cached_games_for_provider(self, provider_name: str) -> list[Game]:
        """Load cached Game objects for a specific provider without hitting the filesystem."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT id, name, source, launcher, executable, icon, logo, hero, cover,
                       installed, favorite, appid, last_played, launch_count,
                       date_added, version, notes, hidden, platform, wine_version, playtime_minutes
                FROM cached_games
                WHERE source = ? AND appid != '888' AND id != 'steam_888' AND lower(name) != 'enabled game'
                """,
                (provider_name.lower().strip(),),
            )
            rows = cursor.fetchall()
            games: list[Game] = []
            for row in rows:
                games.append(
                    Game(
                        id=row["id"],
                        name=row["name"],
                        source=row["source"],
                        launcher=row["launcher"],
                        executable=Path(row["executable"]) if row["executable"] else None,
                        icon=Path(row["icon"]) if row["icon"] else None,
                        logo=Path(row["logo"]) if row["logo"] else None,
                        hero=Path(row["hero"]) if row["hero"] else None,
                        cover=Path(row["cover"]) if row["cover"] else None,
                        installed=bool(row["installed"]),
                        favorite=bool(row["favorite"]),
                        appid=row["appid"],
                        last_played=row["last_played"],
                        launch_count=int(row["launch_count"]),
                        date_added=row["date_added"],
                        version=row["version"],
                        notes=row["notes"],
                        hidden=bool(row["hidden"]) if row["hidden"] is not None else False,
                        platform=row["platform"],
                        wine_version=row["wine_version"],
                        playtime_minutes=int(row["playtime_minutes"]) if row["playtime_minutes"] else 0,
                    )
                )
            return games

    def get_all_cached_games(self) -> list[Game]:
        """Load all cached games directly from SQLite without scanning any providers."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT id, name, source, launcher, executable, icon, logo, hero, cover,
                       installed, favorite, appid, last_played, launch_count,
                       date_added, version, notes, hidden, platform, wine_version, playtime_minutes
                FROM cached_games
                WHERE appid != '888' AND id != 'steam_888' AND lower(name) != 'enabled game'
                ORDER BY favorite DESC, CASE WHEN last_played IS NOT NULL THEN 0 ELSE 1 END, last_played DESC, name ASC
                """
            )
            rows = cursor.fetchall()
            games: list[Game] = []
            for row in rows:
                games.append(
                    Game(
                        id=row["id"],
                        name=row["name"],
                        source=row["source"],
                        launcher=row["launcher"],
                        executable=Path(row["executable"]) if row["executable"] else None,
                        icon=Path(row["icon"]) if row["icon"] else None,
                        logo=Path(row["logo"]) if row["logo"] else None,
                        hero=Path(row["hero"]) if row["hero"] else None,
                        cover=Path(row["cover"]) if row["cover"] else None,
                        installed=bool(row["installed"]),
                        favorite=bool(row["favorite"]),
                        appid=row["appid"],
                        last_played=row["last_played"],
                        launch_count=int(row["launch_count"]),
                        date_added=row["date_added"],
                        version=row["version"],
                        notes=row["notes"],
                        hidden=bool(row["hidden"]) if row["hidden"] is not None else False,
                        platform=row["platform"],
                        wine_version=row["wine_version"],
                        playtime_minutes=int(row["playtime_minutes"]) if row["playtime_minutes"] else 0,
                    )
                )
            return games

    def save_cached_games_for_provider(
        self,
        provider_name: str,
        games: list[Game],
        fingerprint: str | None = None,
    ) -> None:
        """Store newly scanned games for a provider, updating the library cache atomically."""
        now = datetime.now(timezone.utc).isoformat()
        prov_key = provider_name.lower().strip()

        with self._get_connection() as conn:
            # 1. Delete previous games for this provider
            conn.execute("DELETE FROM cached_games WHERE source = ?", (prov_key,))

            # 2. Insert new games with batch executemany for optimal SQLite write speed
            if games:
                rows_to_insert = [
                    (
                        game.id,
                        game.name,
                        game.source,
                        game.launcher,
                        str(game.executable) if game.executable else None,
                        str(game.icon) if game.icon else None,
                        str(game.logo) if game.logo else None,
                        str(game.hero) if game.hero else None,
                        str(game.cover) if game.cover else None,
                        1 if game.installed else 0,
                        1 if game.favorite else 0,
                        game.appid,
                        game.last_played,
                        game.launch_count,
                        fingerprint,
                        now,
                    )
                    for game in games
                ]
                conn.executemany(
                    """
                    INSERT INTO cached_games (
                        id, name, source, launcher, executable, icon, logo, hero, cover,
                        installed, favorite, appid, last_played, launch_count, provider_fingerprint, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows_to_insert,
                )

            # 3. Update fingerprint if provided
            if fingerprint:
                conn.execute(
                    """
                    INSERT INTO provider_fingerprints (provider_name, fingerprint, scanned_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(provider_name) DO UPDATE SET fingerprint = excluded.fingerprint, scanned_at = excluded.scanned_at
                    """,
                    (prov_key, fingerprint, now),
                )

    # ------------------------------------------------------------------
    # Metadata Enrichment & Persistence
    # ------------------------------------------------------------------

    def get_metadata(self, game_id: str) -> GameMetadata | None:
        """Retrieve cached metadata for a specific game identifier.

        Args:
            game_id: Unique game identifier.

        Returns:
            GameMetadata instance if found, else None.
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT id, icon, logo, hero, cover, last_played, launch_count, favorite, updated_at FROM game_metadata WHERE id = ?",
                (game_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None

            return GameMetadata(
                id=row["id"],
                icon=row["icon"],
                logo=row["logo"],
                hero=row["hero"],
                cover=row["cover"],
                last_played=row["last_played"],
                launch_count=int(row["launch_count"]),
                favorite=bool(row["favorite"]),
                updated_at=row["updated_at"],
            )

    def sync_game(self, game: Game) -> Game:
        """Synchronize a single game with the metadata cache."""
        now = datetime.now(timezone.utc).isoformat()
        icon_str = str(game.icon) if game.icon else None
        logo_str = str(game.logo) if game.logo else None
        hero_str = str(game.hero) if game.hero else None
        cover_str = str(game.cover) if game.cover else None

        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT icon, logo, hero, cover, last_played, launch_count, favorite FROM game_metadata WHERE id = ?",
                (game.id,),
            )
            row = cursor.fetchone()

            if row is not None:
                cached_favorite = bool(row["favorite"])
                if cached_favorite and not game.favorite:
                    game.favorite = True

                game.launch_count = int(row["launch_count"])
                game.last_played = row["last_played"]

                if game.icon is None and row["icon"]:
                    cached_icon = Path(row["icon"])
                    if cached_icon.exists():
                        game.icon = cached_icon

                if game.logo is None and row["logo"]:
                    cached_logo = Path(row["logo"])
                    if cached_logo.exists():
                        game.logo = cached_logo

                if game.hero is None and row["hero"]:
                    cached_hero = Path(row["hero"])
                    if cached_hero.exists():
                        game.hero = cached_hero

                if game.cover is None and row["cover"]:
                    cached_cover = Path(row["cover"])
                    if cached_cover.exists():
                        game.cover = cached_cover

                db_icon = icon_str or row["icon"]
                db_logo = logo_str or row["logo"]
                db_hero = hero_str or row["hero"]
                db_cover = cover_str or row["cover"]
                db_fav = 1 if game.favorite else row["favorite"]

                conn.execute(
                    """
                    UPDATE game_metadata
                    SET icon = ?, logo = ?, hero = ?, cover = ?, favorite = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (db_icon, db_logo, db_hero, db_cover, db_fav, now, game.id),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO game_metadata (id, icon, logo, hero, cover, last_played, launch_count, favorite, updated_at)
                    VALUES (?, ?, ?, ?, ?, NULL, 0, ?, ?)
                    """,
                    (game.id, icon_str, logo_str, hero_str, cover_str, 1 if game.favorite else 0, now),
                )

        return game

    def sync_all(self, games: list[Game]) -> list[Game]:
        """Synchronize a collection of games in a single transaction."""
        if not games:
            return []

        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            ids = [g.id for g in games if g.id]
            if not ids:
                return games

            cursor = conn.execute(
                f"SELECT id, icon, logo, hero, cover, last_played, launch_count, favorite FROM game_metadata WHERE id IN ({','.join(['?']*len(ids))})",
                ids,
            )
            existing_map: dict[str, sqlite3.Row] = {row["id"]: row for row in cursor.fetchall()}

            for game in games:
                if not game.id:
                    continue

                icon_str = str(game.icon) if game.icon else None
                logo_str = str(game.logo) if game.logo else None
                hero_str = str(game.hero) if game.hero else None
                cover_str = str(game.cover) if game.cover else None

                if game.id in existing_map:
                    row = existing_map[game.id]
                    if bool(row["favorite"]) and not game.favorite:
                        game.favorite = True

                    game.launch_count = int(row["launch_count"])
                    game.last_played = row["last_played"]

                    if game.icon is None and row["icon"]:
                        cached_icon = Path(row["icon"])
                        if cached_icon.exists():
                            game.icon = cached_icon

                    if game.logo is None and row["logo"]:
                        cached_logo = Path(row["logo"])
                        if cached_logo.exists():
                            game.logo = cached_logo

                    if game.hero is None and row["hero"]:
                        cached_hero = Path(row["hero"])
                        if cached_hero.exists():
                            game.hero = cached_hero

                    if game.cover is None and row["cover"]:
                        cached_cover = Path(row["cover"])
                        if cached_cover.exists():
                            game.cover = cached_cover

                    db_icon = icon_str or row["icon"]
                    db_logo = logo_str or row["logo"]
                    db_hero = hero_str or row["hero"]
                    db_cover = cover_str or row["cover"]
                    db_fav = 1 if game.favorite else row["favorite"]

                    conn.execute(
                        """
                        UPDATE game_metadata
                        SET icon = ?, logo = ?, hero = ?, cover = ?, favorite = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (db_icon, db_logo, db_hero, db_cover, db_fav, now, game.id),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO game_metadata (id, icon, logo, hero, cover, last_played, launch_count, favorite, updated_at)
                        VALUES (?, ?, ?, ?, ?, NULL, 0, ?, ?)
                        """,
                        (game.id, icon_str, logo_str, hero_str, cover_str, 1 if game.favorite else 0, now),
                    )

        logger.debug("Synchronized %d games with metadata cache", len(games))
        return games

    def record_launch(self, game_id: str) -> None:
        """Increment the launch count and record the last played timestamp for a game."""
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT launch_count FROM game_metadata WHERE id = ?",
                (game_id,),
            )
            row = cursor.fetchone()

            if row is not None:
                new_count = int(row["launch_count"]) + 1
                conn.execute(
                    """
                    UPDATE game_metadata
                    SET launch_count = ?, last_played = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (new_count, now, now, game_id),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO game_metadata (id, icon, logo, hero, cover, last_played, launch_count, favorite, updated_at)
                    VALUES (?, NULL, NULL, NULL, NULL, ?, 1, 0, ?)
                    """,
                    (game_id, now, now),
                )

            # Also update cached_games if present
            conn.execute(
                """
                UPDATE cached_games
                SET launch_count = launch_count + 1, last_played = ?, updated_at = ?
                WHERE id = ?
                """,
                (now, now, game_id),
            )

        logger.info("Recorded launch for game '%s'", game_id)

    def set_favorite(self, game_id: str, favorite: bool) -> None:
        """Update favorite toggle for a game in the database."""
        now = datetime.now(timezone.utc).isoformat()
        fav_val = 1 if favorite else 0
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT id FROM game_metadata WHERE id = ?", (game_id,))
            if cursor.fetchone() is not None:
                conn.execute(
                    "UPDATE game_metadata SET favorite = ?, updated_at = ? WHERE id = ?",
                    (fav_val, now, game_id),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO game_metadata (id, icon, logo, hero, cover, last_played, launch_count, favorite, updated_at)
                    VALUES (?, NULL, NULL, NULL, NULL, NULL, 0, ?, ?)
                    """,
                    (game_id, fav_val, now),
                )

            conn.execute(
                "UPDATE cached_games SET favorite = ?, updated_at = ? WHERE id = ?",
                (fav_val, now, game_id),
            )

    def update_game_properties(
        self,
        game_id: str,
        name: str | None = None,
        executable: Path | str | None = None,
        launcher: str | None = None,
        icon: Path | str | None = None,
        cover: Path | str | None = None,
        logo: Path | str | None = None,
        hero: Path | str | None = None,
        favorite: bool | None = None,
        notes: str | None = None,
        version: str | None = None,
        hidden: bool | None = None,
        platform: str | None = None,
        wine_version: str | None = None,
    ) -> bool:
        """Update user-editable properties and artwork paths for a game in SQLite."""
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT name, executable, launcher, icon, cover, logo, hero, favorite, notes, version, hidden, platform, wine_version FROM cached_games WHERE id = ?",
                (game_id,),
            )
            row = cursor.fetchone()

            if not row:
                conn.execute(
                    """
                    INSERT INTO cached_games (id, name, source, launcher, executable, icon, cover, logo, hero, installed, favorite, notes, version, hidden, platform, wine_version, updated_at)
                    VALUES (?, ?, 'native', 'native', ?, ?, ?, ?, ?, 1, 0, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        game_id,
                        name or game_id,
                        str(executable).strip() if executable else None,
                        str(icon).strip() if icon else None,
                        str(cover).strip() if cover else None,
                        str(logo).strip() if logo else None,
                        str(hero).strip() if hero else None,
                        notes,
                        version,
                        1 if hidden else 0,
                        platform,
                        wine_version,
                        now,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO game_metadata (id, icon, cover, logo, hero, favorite, notes, version, hidden, platform, wine_version, updated_at)
                    VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        icon = COALESCE(excluded.icon, game_metadata.icon),
                        cover = COALESCE(excluded.cover, game_metadata.cover),
                        logo = COALESCE(excluded.logo, game_metadata.logo),
                        hero = COALESCE(excluded.hero, game_metadata.hero),
                        updated_at = excluded.updated_at
                    """,
                    (
                        game_id,
                        str(icon).strip() if icon else None,
                        str(cover).strip() if cover else None,
                        str(logo).strip() if logo else None,
                        str(hero).strip() if hero else None,
                        notes,
                        version,
                        1 if hidden else 0,
                        platform,
                        wine_version,
                        now,
                    ),
                )
                return True

            new_name = name.strip() if name and name.strip() else row["name"]
            new_exe = str(executable).strip() if executable is not None else row["executable"]
            new_launcher = launcher.strip() if launcher and launcher.strip() else row["launcher"]
            new_icon = str(icon).strip() if icon is not None else row["icon"]
            new_cover = str(cover).strip() if cover is not None else row["cover"]
            new_logo = str(logo).strip() if logo is not None else row["logo"]
            new_hero = str(hero).strip() if hero is not None else row["hero"]
            new_fav = (1 if favorite else 0) if favorite is not None else row["favorite"]
            new_notes = notes if notes is not None else row["notes"]
            new_version = version if version is not None else row["version"]
            new_hidden = (1 if hidden else 0) if hidden is not None else (row["hidden"] or 0)
            new_platform = platform if platform is not None else row["platform"]
            new_wine_version = wine_version if wine_version is not None else row["wine_version"]

            conn.execute(
                """
                UPDATE cached_games
                SET name = ?, executable = ?, launcher = ?, icon = ?, cover = ?, logo = ?, hero = ?,
                    favorite = ?, notes = ?, version = ?, hidden = ?, platform = ?, wine_version = ?, updated_at = ?
                WHERE id = ?
                """,
                (new_name, new_exe, new_launcher, new_icon, new_cover, new_logo, new_hero,
                 new_fav, new_notes, new_version, new_hidden, new_platform, new_wine_version, now, game_id),
            )
            conn.execute(
                """
                INSERT INTO game_metadata (id, icon, cover, logo, hero, favorite, notes, version, hidden, platform, wine_version, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    icon = COALESCE(excluded.icon, game_metadata.icon),
                    cover = COALESCE(excluded.cover, game_metadata.cover),
                    logo = COALESCE(excluded.logo, game_metadata.logo),
                    hero = COALESCE(excluded.hero, game_metadata.hero),
                    favorite = excluded.favorite,
                    updated_at = excluded.updated_at
                """,
                (game_id, new_icon, new_cover, new_logo, new_hero, new_fav,
                 new_notes, new_version, new_hidden, new_platform, new_wine_version, now),
            )
            return True

    def toggle_favorite(self, game_id: str) -> bool:
        """Toggle favorite state for a game and return the new state."""
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT favorite FROM game_metadata WHERE id = ?", (game_id,))
            row = cursor.fetchone()
            if row is not None:
                new_status = not bool(row["favorite"])
                fav_val = 1 if new_status else 0
                conn.execute(
                    "UPDATE game_metadata SET favorite = ?, updated_at = ? WHERE id = ?",
                    (fav_val, now, game_id),
                )
                conn.execute(
                    "UPDATE cached_games SET favorite = ?, updated_at = ? WHERE id = ?",
                    (fav_val, now, game_id),
                )
                return new_status
            else:
                conn.execute(
                    """
                    INSERT INTO game_metadata (id, icon, logo, hero, cover, last_played, launch_count, favorite, updated_at)
                    VALUES (?, NULL, NULL, NULL, NULL, NULL, 0, 1, ?)
                    """,
                    (game_id, now),
                )
                conn.execute(
                    "UPDATE cached_games SET favorite = 1, updated_at = ? WHERE id = ?",
                    (now, game_id),
                )
                return True

    def get_favorites(self) -> set[str]:
        """Return set of game IDs currently marked as favorites."""
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT id FROM game_metadata WHERE favorite = 1")
            return {row["id"] for row in cursor.fetchall()}

    def get_recently_played_ids(self, limit: int = 10) -> list[str]:
        """Return ordered list of recently launched game IDs."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT id FROM game_metadata WHERE last_played IS NOT NULL ORDER BY last_played DESC LIMIT ?",
                (limit,),
            )
            return [row["id"] for row in cursor.fetchall()]


# ---------------------------------------------------------------------------
# Backwards-compatible alias
# ---------------------------------------------------------------------------

LibraryCache = MetadataCache
