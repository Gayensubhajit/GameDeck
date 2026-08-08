"""Library statistics reporting engine for GameDeck."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from gamedeck.database import MetadataCache
from gamedeck.models import Game

__all__ = ["LibraryStats", "LibraryStatsProvider"]

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class GameSession:
    """Represents a discrete gameplay session."""

    id: str
    game_id: str
    start_time: str
    end_time: str | None = None
    duration_seconds: int = 0


@dataclass(slots=True, frozen=True)
class LibraryStats:
    """Library statistics snapshot."""

    total_games: int
    total_playtime_minutes: int
    favorites_count: int
    installed_count: int
    hidden_count: int
    launcher_counts: dict[str, int]
    most_played: list[tuple[str, int]]
    last_played_title: str | None = None
    last_played_time: str | None = None
    longest_session_mins: int = 0
    total_sessions_count: int = 0

    def formatted_summary(self) -> str:
        """Return formatted multi-line summary string of library statistics."""
        hours = self.total_playtime_minutes // 60
        mins = self.total_playtime_minutes % 60
        playtime_str = f"{hours}h {mins}m" if hours > 0 else f"{mins}m"

        dist_str = ", ".join(f"{k.capitalize()}: {v}" for k, v in self.launcher_counts.items()) if self.launcher_counts else "None"
        most_played_str = ", ".join(f"{title} ({cnt}x)" for title, cnt in self.most_played[:5]) if self.most_played else "None"
        last_played_str = f"{self.last_played_title} ({self.last_played_time[:10]})" if self.last_played_title and self.last_played_time else "None"

        return (
            f"📊 GameDeck Library Statistics\n"
            f"─────────────────────────────────────\n"
            f"Total Games:       {self.total_games}\n"
            f"Installed Games:   {self.installed_count}\n"
            f"Favorite Games:    {self.favorites_count}\n"
            f"Hidden Games:      {self.hidden_count}\n"
            f"Total Playtime:    {playtime_str}\n"
            f"Total Sessions:    {self.total_sessions_count}\n"
            f"Longest Session:   {self.longest_session_mins}m\n"
            f"Last Played Game:  {last_played_str}\n"
            f"Most Played:       {most_played_str}\n"
            f"Launcher Mix:      {dist_str}"
        )


@dataclass(slots=True)
class LibraryStatsProvider:
    """Calculates aggregate library statistics and records game sessions in SQLite."""

    metadata_cache: MetadataCache = field(default_factory=MetadataCache)

    def record_session(self, game_id: str, duration_seconds: int) -> None:
        """Record a completed gameplay session in SQLite."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        sid = f"sess_{game_id}_{int(datetime.now(timezone.utc).timestamp())}"
        with self.metadata_cache._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO game_sessions (id, game_id, start_time, end_time, duration_seconds)
                VALUES (?, ?, ?, ?, ?)
                """,
                (sid, game_id, now, now, duration_seconds),
            )
            mins = max(1, duration_seconds // 60)
            conn.execute(
                "UPDATE cached_games SET playtime_minutes = playtime_minutes + ? WHERE id = ?",
                (mins, game_id),
            )
            conn.execute(
                "UPDATE game_metadata SET playtime_minutes = playtime_minutes + ? WHERE id = ?",
                (mins, game_id),
            )

    def calculate_stats(self, games: list[Game] | None = None) -> LibraryStats:
        """Calculate statistics across provided games or all SQLite cached games."""
        if games is None:
            games = self.metadata_cache.get_all_cached_games()

        total = len(games)
        favs = sum(1 for g in games if g.favorite)
        inst = sum(1 for g in games if g.installed)
        hidden = sum(1 for g in games if getattr(g, "hidden", False))

        total_mins = sum(getattr(g, "playtime_minutes", 0) for g in games)

        launchers: dict[str, int] = {}
        for g in games:
            key = (g.source or g.launcher or "unknown").lower()
            launchers[key] = launchers.get(key, 0) + 1

        # Most played
        played_games = [g for g in games if g.launch_count > 0]
        played_games.sort(key=lambda g: g.launch_count, reverse=True)
        most_played = [(g.name, g.launch_count) for g in played_games[:5]]

        # Last played
        recent = [g for g in games if g.last_played]
        recent.sort(key=lambda g: g.last_played or "", reverse=True)
        last_title = recent[0].name if recent else None
        last_time = recent[0].last_played if recent else None

        total_sess_cnt = 0
        longest_sess_mins = 0
        with self.metadata_cache._get_connection() as conn:
            row = conn.execute("SELECT COUNT(*), MAX(duration_seconds) FROM game_sessions").fetchone()
            if row:
                total_sess_cnt = row[0] or 0
                longest_sess_mins = (row[1] or 0) // 60

        return LibraryStats(
            total_games=total,
            total_playtime_minutes=total_mins,
            favorites_count=favs,
            installed_count=inst,
            hidden_count=hidden,
            launcher_counts=launchers,
            most_played=most_played,
            last_played_title=last_title,
            last_played_time=last_time,
            longest_session_mins=longest_sess_mins,
            total_sessions_count=total_sess_cnt,
        )
