"""SQLite metadata cache and persistence layer for GameDeck."""

from __future__ import annotations

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
    "MetadataCache",
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
    """Cached game metadata record.

    Attributes:
        id: Unique identifier for the game.
        icon: Path string to the game icon file.
        logo: Path string to the game logo image.
        hero: Path string to the game hero/banner image.
        cover: Path string to the game cover art image.
        last_played: ISO timestamp string of the last launch time.
        launch_count: Total number of times launched via GameDeck.
        favorite: Whether marked as favorite.
        updated_at: Timestamp string of the record update.
    """

    id: str
    icon: str | None = None
    logo: str | None = None
    hero: str | None = None
    cover: str | None = None
    last_played: str | None = None
    launch_count: int = 0
    favorite: bool = False
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass(slots=True)
class MetadataCache:
    """SQLite-backed metadata cache for icons, covers, logos, heroes, play statistics, and favorites.

    Attributes:
        db_path: Path to the SQLite database file.
    """

    db_path: Path = field(default_factory=get_default_db_path)

    def __post_init__(self) -> None:
        """Initialize database directory and schema."""
        self._init_db()

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager yielding an open SQLite connection."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=5.0,
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as err:
            conn.rollback()
            logger.error("Database operation failed on '%s': %s", self.db_path, err)
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        """Create database tables, indices, and columns if they do not already exist."""
        with self._get_connection() as conn:
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
            # Ensure schema migration for logo and hero columns
            cursor = conn.execute("PRAGMA table_info(game_metadata)")
            existing_cols = {row[1] for row in cursor.fetchall()}
            if "logo" not in existing_cols:
                conn.execute("ALTER TABLE game_metadata ADD COLUMN logo TEXT")
            if "hero" not in existing_cols:
                conn.execute("ALTER TABLE game_metadata ADD COLUMN hero TEXT")

            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_game_metadata_favorite ON game_metadata(favorite)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_game_metadata_last_played ON game_metadata(last_played)"
            )

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
        """Synchronize a single game with the metadata cache.

        Merges existing cached play statistics, last played timestamps, and favorite status,
        and automatically updates newly discovered icon and artwork paths in the database.

        Args:
            game: Game model instance to synchronize.

        Returns:
            The enriched Game instance.
        """
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

                # Fallback to cached paths if missing on model
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
        """Synchronize a collection of games in a single transaction.

        Args:
            games: List of Game instances from all library providers.

        Returns:
            List of synchronized and enriched Game instances.
        """
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
        """Increment the launch count and record the last played timestamp for a game.

        Args:
            game_id: Unique game identifier.
        """
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

        logger.info("Recorded launch for game '%s'", game_id)

    def set_favorite(self, game_id: str, favorite: bool) -> None:
        """Update favorite toggle for a game in the database.

        Args:
            game_id: Unique game identifier.
            favorite: True to mark as favorite, False otherwise.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT id FROM game_metadata WHERE id = ?", (game_id,))
            if cursor.fetchone() is not None:
                conn.execute(
                    "UPDATE game_metadata SET favorite = ?, updated_at = ? WHERE id = ?",
                    (1 if favorite else 0, now, game_id),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO game_metadata (id, icon, logo, hero, cover, last_played, launch_count, favorite, updated_at)
                    VALUES (?, NULL, NULL, NULL, NULL, NULL, 0, ?, ?)
                    """,
                    (game_id, 1 if favorite else 0, now),
                )

    def toggle_favorite(self, game_id: str) -> bool:
        """Toggle favorite state for a game and return the new state.

        Args:
            game_id: Unique game identifier.

        Returns:
            The new boolean favorite status.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT favorite FROM game_metadata WHERE id = ?", (game_id,))
            row = cursor.fetchone()
            if row is not None:
                new_status = not bool(row["favorite"])
                conn.execute(
                    "UPDATE game_metadata SET favorite = ?, updated_at = ? WHERE id = ?",
                    (1 if new_status else 0, now, game_id),
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
                return True

    def get_favorites(self) -> set[str]:
        """Return set of game IDs currently marked as favorites."""
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT id FROM game_metadata WHERE favorite = 1")
            return {row["id"] for row in cursor.fetchall()}

    def get_recently_played_ids(self, limit: int = 10) -> list[str]:
        """Return ordered list of recently launched game IDs.

        Args:
            limit: Maximum number of recent game IDs to return.

        Returns:
            List of game IDs ordered by last_played descending.
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT id FROM game_metadata WHERE last_played IS NOT NULL ORDER BY last_played DESC LIMIT ?",
                (limit,),
            )
            return [row["id"] for row in cursor.fetchall()]
