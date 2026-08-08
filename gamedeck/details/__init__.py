"""Game Details system for GameDeck providing cached game information without rescanning providers."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gamedeck.database import MetadataCache
from gamedeck.models import Game

__all__ = [
    "GameDetails",
    "GameDetailsProvider",
]

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class GameDetails:
    """Immutable detailed view of a game's runtime and library metadata."""

    id: str
    title: str
    source: str
    provider_name: str
    launcher: str
    install_path: Path | None = None
    executable: Path | None = None
    launch_count: int = 0
    last_played: str | None = None
    favorite: bool = False
    date_added: str | None = None
    version: str | None = None
    notes: str | None = None
    hidden: bool = False
    platform: str | None = None
    wine_version: str | None = None
    playtime_minutes: int = 0
    appid: str | None = None
    icon: Path | None = None
    cover: Path | None = None
    logo: Path | None = None
    hero: Path | None = None
    tags: list[str] = field(default_factory=list)
    collections: list[str] = field(default_factory=list)

    def formatted_summary(self) -> str:
        """Return formatted multi-line summary string for dialog display or CLI output."""
        fav_icon = "★ Yes" if self.favorite else "No"
        last_str = self.last_played[:19] if self.last_played else "Never"
        exec_str = str(self.executable) if self.executable else "None"
        install_str = str(self.install_path) if self.install_path else "None"
        
        is_wine_env = (self.source or "").lower() in ("steam", "lutris", "heroic", "wine") or (self.launcher or "").lower() in ("wine", "proton", "bottles")
        plat_str = self.platform or ("Windows (Proton/Wine)" if is_wine_env else "Linux Native")
        wine_str = self.wine_version or ("Wine-GE / Proton" if is_wine_env else "N/A")
        ver_str = self.version or "1.0"
        notes_str = self.notes or "None"
        tags_str = ", ".join(self.tags) if self.tags else "None"
        colls_str = ", ".join(self.collections) if self.collections else "None"
        
        cover_str = str(self.cover) if self.cover else "None"
        hero_str = str(self.hero) if self.hero else "None"
        logo_str = str(self.logo) if self.logo else "None"
        icon_str = str(self.icon) if self.icon else "None"

        return (
            f"Title:        {self.title}\n"
            f"Source:       {self.source} ({self.provider_name})\n"
            f"Launcher:     {self.launcher}\n"
            f"Platform:     {plat_str}\n"
            f"Wine/Runner:  {wine_str}\n"
            f"Install Path: {install_str}\n"
            f"Executable:   {exec_str}\n"
            f"Version:      {ver_str}\n"
            f"Launch Count: {self.launch_count}\n"
            f"Last Played:  {last_str}\n"
            f"Favorite:     {fav_icon}\n"
            f"Collections:  {colls_str}\n"
            f"Tags:         {tags_str}\n"
            f"Notes:        {notes_str}\n"
            f"Cover Art:    {cover_str}\n"
            f"Hero Banner:  {hero_str}\n"
            f"Logo Art:     {logo_str}\n"
            f"Icon Path:    {icon_str}"
        )


PROVIDER_DISPLAY_NAMES: dict[str, str] = {
    "steam": "Steam",
    "lutris": "Lutris",
    "heroic": "Heroic Games Launcher",
    "native": "Native Linux Application",
    "filesystem": "Local Filesystem",
}


@dataclass(slots=True)
class GameDetailsProvider:
    """Provides detailed metadata for games on-demand without filesystem rescanning.

    Uses SQLite cached metadata and stored game records to eliminate redundant disk I/O.

    Attributes:
        metadata_cache: Persistence cache instance.
    """

    metadata_cache: MetadataCache = field(default_factory=MetadataCache)

    def get_details(self, game_or_id: Game | str) -> GameDetails | None:
        """Retrieve complete GameDetails for a given Game instance or game ID."""
        if isinstance(game_or_id, Game):
            return self._build_details_from_game(game_or_id)

        # Lookup directly from SQLite cached_games
        game_id = str(game_or_id).strip()
        with self.metadata_cache._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT id, name, source, launcher, executable, icon, logo, hero, cover,
                       installed, favorite, appid, last_played, launch_count
                FROM cached_games
                WHERE id = ?
                """,
                (game_id,),
            )
            row = cursor.fetchone()
            if row is not None:
                game = Game(
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
                )
                return self._build_details_from_game(game)

        return None

    def _build_details_from_game(self, game: Game) -> GameDetails:
        """Construct GameDetails from a Game object, inferring install_path if possible."""
        prov_key = (game.source or "").lower().strip()
        provider_name = PROVIDER_DISPLAY_NAMES.get(prov_key, prov_key.capitalize())

        # Determine install_path: executable parent if file, or executable itself if directory
        install_path: Path | None = None
        if game.executable is not None:
            p = Path(game.executable)
            install_path = p if p.is_dir() else p.parent

        # Fetch latest dynamic metadata
        meta = self.metadata_cache.get_metadata(game.id)
        launch_count = meta.launch_count if meta else game.launch_count
        last_played = meta.last_played if meta else game.last_played
        favorite = meta.favorite if meta else game.favorite

        from gamedeck.tags import TagManager
        tag_mgr = TagManager(metadata_cache=self.metadata_cache)
        game_tags = tag_mgr.get_tags_for_game(game.id)

        from gamedeck.collections import CollectionManager
        coll_mgr = CollectionManager(metadata_cache=self.metadata_cache)
        game_colls = [c.name for c in coll_mgr.get_custom_collections([game]) if any(g.id == game.id for g in c.games)]

        from gamedeck.artwork import ArtworkCache
        art_cache = ArtworkCache()
        
        icon_path = game.icon or (meta.icon if meta else None) or art_cache.get_artwork(game.id, "icons")
        cover_path = game.cover or (meta.cover if meta else None) or art_cache.get_artwork(game.id, "covers")
        logo_path = game.logo or (meta.logo if meta else None) or art_cache.get_artwork(game.id, "logos")
        hero_path = game.hero or (meta.hero if meta else None) or art_cache.get_artwork(game.id, "heroes")

        return GameDetails(
            id=game.id,
            title=game.name,
            source=game.source,
            provider_name=provider_name,
            launcher=game.launcher,
            install_path=install_path,
            executable=Path(game.executable) if game.executable else None,
            launch_count=launch_count,
            last_played=last_played,
            favorite=favorite,
            date_added=getattr(game, "date_added", None),
            version=getattr(game, "version", None),
            notes=getattr(game, "notes", None),
            hidden=getattr(game, "hidden", False),
            platform=getattr(game, "platform", None),
            wine_version=getattr(game, "wine_version", None),
            playtime_minutes=getattr(game, "playtime_minutes", 0),
            appid=game.appid,
            icon=Path(icon_path) if icon_path else None,
            cover=Path(cover_path) if cover_path else None,
            logo=Path(logo_path) if logo_path else None,
            hero=Path(hero_path) if hero_path else None,
            tags=game_tags,
            collections=game_colls,
        )
