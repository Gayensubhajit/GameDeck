"""Dynamic Game Tagging system for GameDeck backed by SQLite persistence."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from gamedeck.database import MetadataCache
from gamedeck.models import Game

__all__ = [
    "Tag",
    "TagManager",
    "COMMON_TAGS",
]

logger = logging.getLogger(__name__)

COMMON_TAGS: list[str] = [
    "RPG",
    "Soulslike",
    "FPS",
    "Indie",
    "Co-op",
    "Finished",
    "Wishlist",
    "Action",
    "Adventure",
    "Strategy",
    "Simulation",
    "Multiplayer",
    "Casual",
]


@dataclass(slots=True, frozen=True)
class Tag:
    """Represents a game metadata tag.

    Attributes:
        name: Clean capitalized display name (e.g. 'Soulslike', 'RPG', 'Wishlist').
        slug: Normalized lowercase identifier (e.g. 'soulslike', 'rpg', 'co-op').
        count: Number of games currently tagged with this label.
    """

    name: str
    slug: str
    count: int = 0


@dataclass(slots=True)
class TagManager:
    """Manages creation, assignment, querying, and search indexing for game tags in SQLite.

    Attributes:
        metadata_cache: Persistence cache instance.
    """

    metadata_cache: MetadataCache = field(default_factory=MetadataCache)

    def __post_init__(self) -> None:
        """Ensure tags and game_tags tables exist in SQLite."""
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        """Create tables for persistent tag storage and game associations."""
        with self.metadata_cache._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tags (
                    slug TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS game_tags (
                    game_id TEXT NOT NULL,
                    tag_slug TEXT NOT NULL,
                    tagged_at TEXT NOT NULL,
                    PRIMARY KEY (game_id, tag_slug),
                    FOREIGN KEY (tag_slug) REFERENCES tags(slug) ON DELETE CASCADE
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_game_tags_game ON game_tags(game_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_game_tags_tag ON game_tags(tag_slug)")

            # Seed common default tags
            now = datetime.now(timezone.utc).isoformat()
            for tag_name in COMMON_TAGS:
                slug = self.slugify(tag_name)
                conn.execute(
                    """
                    INSERT OR IGNORE INTO tags (slug, name, created_at)
                    VALUES (?, ?, ?)
                    """,
                    (slug, tag_name.strip(), now),
                )

    @staticmethod
    def slugify(tag_name: str) -> str:
        """Normalize a tag string to a clean identifier slug."""
        return tag_name.strip().lower().replace(" ", "_")

    # -------------------------------------------------------------------------
    # Tag Management
    # -------------------------------------------------------------------------

    def create_tag(self, name: str) -> str:
        """Create a new tag in SQLite.

        Args:
            name: Display name for the tag (e.g. 'Soulslike').

        Returns:
            The normalized tag slug.
        """
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Tag name cannot be empty.")

        slug = self.slugify(clean_name)
        now = datetime.now(timezone.utc).isoformat()

        with self.metadata_cache._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO tags (slug, name, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(slug) DO UPDATE SET name = excluded.name
                """,
                (slug, clean_name, now),
            )
        logger.info("Created tag '%s' [%s]", clean_name, slug)
        return slug

    def delete_tag(self, tag_name_or_slug: str) -> bool:
        """Delete a tag and remove it from all games."""
        slug = self.slugify(tag_name_or_slug)
        with self.metadata_cache._get_connection() as conn:
            cursor = conn.execute("DELETE FROM tags WHERE slug = ?", (slug,))
            conn.execute("DELETE FROM game_tags WHERE tag_slug = ?", (slug,))
            return cursor.rowcount > 0

    def get_all_tags(self) -> list[Tag]:
        """Return all registered tags with game assignment counts."""
        with self.metadata_cache._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT t.slug, t.name, COUNT(gt.game_id) as count
                FROM tags t
                LEFT JOIN game_tags gt ON t.slug = gt.tag_slug
                GROUP BY t.slug, t.name
                ORDER BY t.name ASC
                """
            )
            return [
                Tag(name=row["name"], slug=row["slug"], count=int(row["count"]))
                for row in cursor.fetchall()
            ]

    # -------------------------------------------------------------------------
    # Game Tag Associations
    # -------------------------------------------------------------------------

    def add_tag_to_game(self, game_id: str, tag_name: str) -> bool:
        """Assign a tag to a game, creating the tag if it doesn't already exist.

        Args:
            game_id: Target game identifier.
            tag_name: Tag label (e.g. 'Soulslike', 'RPG', 'Wishlist').

        Returns:
            True if newly assigned, False if already present.
        """
        slug = self.create_tag(tag_name)
        now = datetime.now(timezone.utc).isoformat()

        with self.metadata_cache._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO game_tags (game_id, tag_slug, tagged_at)
                VALUES (?, ?, ?)
                """,
                (game_id, slug, now),
            )
            return cursor.rowcount > 0

    def remove_tag_from_game(self, game_id: str, tag_name: str) -> bool:
        """Remove a tag assignment from a game."""
        slug = self.slugify(tag_name)
        with self.metadata_cache._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM game_tags WHERE game_id = ? AND tag_slug = ?",
                (game_id, slug),
            )
            return cursor.rowcount > 0

    def set_game_tags(self, game_id: str, tag_names: list[str]) -> None:
        """Overwrite all tags for a game with a new list."""
        with self.metadata_cache._get_connection() as conn:
            conn.execute("DELETE FROM game_tags WHERE game_id = ?", (game_id,))

        for name in tag_names:
            self.add_tag_to_game(game_id, name)

    def get_tags_for_game(self, game_id: str) -> list[str]:
        """Retrieve list of tag names assigned to a game."""
        with self.metadata_cache._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT t.name FROM tags t
                JOIN game_tags gt ON t.slug = gt.tag_slug
                WHERE gt.game_id = ?
                ORDER BY t.name ASC
                """,
                (game_id,),
            )
            return [row["name"] for row in cursor.fetchall()]

    def get_games_for_tag(self, tag_name_or_slug: str, all_games: list[Game]) -> list[Game]:
        """Return all Game instances matching a tag query."""
        slug = self.slugify(tag_name_or_slug)
        with self.metadata_cache._get_connection() as conn:
            cursor = conn.execute(
                "SELECT game_id FROM game_tags WHERE tag_slug = ?",
                (slug,),
            )
            matched_ids = {row["game_id"] for row in cursor.fetchall()}

        return [g for g in all_games if g.id in matched_ids]

    def get_all_game_tags_map(self) -> dict[str, list[str]]:
        """Return dictionary mapping game_id to list of assigned tag names."""
        result: dict[str, list[str]] = {}
        with self.metadata_cache._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT gt.game_id, t.name
                FROM game_tags gt
                JOIN tags t ON gt.tag_slug = t.slug
                ORDER BY t.name ASC
                """
            )
            for row in cursor.fetchall():
                gid = row["game_id"]
                result.setdefault(gid, []).append(row["name"])
        return result
