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

    def format_header_pango(self) -> str:
        """Transform game metadata into a premium information header with proper typography hierarchy.

        Displays:
        • Hero Artwork / Game Icon fallback
        • Game Logo
        • Game Title (Large Title)
        • Launcher Badge (Badges instead of plain text)
        • Platform Badge
        • Wine Version Badge
        • Version Badge
        • Playtime
        • Last Played
        • Launch Count
        • Favorite Indicator
        """
        # 1. Launcher Badge
        launcher_raw = (self.launcher or self.source or "native").upper()
        launcher_badge = f"<span background='#00e69926' foreground='#00e699' weight='bold'> [{launcher_raw}] </span>"

        # 2. Platform Badge
        is_wine_env = (
            (self.source or "").lower() in ("steam", "lutris", "heroic", "wine", "filesystem")
            or (self.launcher or "").lower() in ("wine", "proton", "bottles")
        )
        plat_str = self.platform or ("Windows" if is_wine_env else "Linux")
        plat_badge = f"<span background='#0284c726' foreground='#38bdf8' weight='bold'> [{plat_str.upper()}] </span>"

        # 3. Wine Version Badge
        wine_str = self.wine_version or ("Wine-GE / Proton" if is_wine_env else "Native")
        wine_badge = f"<span background='#a855f726' foreground='#c084fc' weight='bold'> [{wine_str.upper()}] </span>"

        # 4. Version Badge
        ver_str = self.version or "1.0"
        ver_tag = f"v{ver_str}" if not ver_str.startswith("v") else ver_str
        ver_badge = f"<span background='#47556940' foreground='#e2e8f0' weight='bold'> [{ver_tag}] </span>"

        # 5. Favorite Indicator
        fav_icon = "★" if self.favorite else "☆"
        fav_str = "★ FAVORITE" if self.favorite else "☆ STANDARD"
        fav_bg = "#eab30826" if self.favorite else "#33415540"
        fav_fg = "#facc15" if self.favorite else "#94a3b8"
        fav_badge = f"<span background='{fav_bg}' foreground='{fav_fg}' weight='bold'> {fav_str} </span>"

        # 6. Playtime
        hours = self.playtime_minutes // 60
        mins = self.playtime_minutes % 60
        pt_str = f"{hours}h {mins}m" if hours > 0 else f"{mins}m"

        # 7. Last Played & Launch Count
        last_str = self.last_played[:10] if self.last_played else "Never"
        date_add_str = (self.date_added or "")[:10] or "Recent"

        # 8. Hero, Logo, Icon & Artwork Fallbacks
        hero_str = str(self.hero.name) if self.hero else None
        logo_str = str(self.logo.name) if self.logo else None
        icon_str = str(self.icon.name) if self.icon else (str(self.cover.name) if self.cover else "[Fallback Icon]")

        logo_tag = f"  <span foreground='#38bdf8' size='small' weight='bold'>✨ {logo_str}</span>" if logo_str else ""

        if hero_str:
            art_status = f"🖼️ <b>Hero Artwork:</b> <span foreground='#00e699'>{hero_str}</span>"
            if logo_str:
                art_status += f"  •  ✨ <b>Logo:</b> <span foreground='#38bdf8'>{logo_str}</span>"
        else:
            art_status = f"🎮 <b>Game Icon:</b> <span foreground='#38bdf8'>{icon_str}</span>  •  🎨 <b>Banner:</b> <span foreground='#00e699'>Gradient Glassmorphism Active</span>"

        # Compose multi-line premium information header
        # Line 1: Large Game Title + Logo Tag + Favorite Badge
        line1 = f"<span font_desc='Outfit Bold 15' size='large' weight='heavy' foreground='#ffffff'><b>{self.title}</b></span>{logo_tag}  {fav_badge}"
        # Line 2: Badges row (Launcher, Platform, Wine, Version)
        line2 = f"<b>Launcher:</b> {launcher_badge}  •  <b>Platform:</b> {plat_badge}  •  <b>Wine:</b> {wine_badge}  •  <b>Version:</b> {ver_badge}"
        # Line 3: Small metadata row (Playtime, Last Played, Launches, Date Added)
        line3 = f"<span size='small' foreground='#94a3b8'>⏱ <b>Playtime:</b> <span foreground='#f8fafc' weight='bold'>{pt_str}</span>  •  📅 <b>Last Played:</b> <span foreground='#f8fafc' weight='bold'>{last_str}</span>  •  🔢 <b>Launches:</b> <span foreground='#f8fafc' weight='bold'>{self.launch_count}</span>  •  ➕ <b>Added:</b> <span foreground='#f8fafc'>{date_add_str}</span></span>"
        # Line 4: Artwork & Visual status (Never looks empty)
        line4 = f"<span size='small' foreground='#94a3b8'>{art_status}</span>"

        return f"{line1}\n{line2}\n{line3}\n{line4}"

    def formatted_summary(self) -> str:
        """Return formatted multi-line summary string for dialog display or CLI output."""
        fav_icon = "★ Yes" if self.favorite else "No"
        last_str = self.last_played[:19] if self.last_played else "Never"
        exec_str = str(self.executable) if self.executable else "None"
        install_str = str(self.install_path) if self.install_path else "None"
        
        is_wine_env = (self.source or "").lower() in ("steam", "lutris", "heroic", "wine", "filesystem") or (self.launcher or "").lower() in ("wine", "proton", "bottles")
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

    def formatted_panel(self) -> str:
        """Format a live rich details panel string with all metadata fields and artwork fallbacks."""
        launcher_badge = f"[{self.launcher.upper()}]" if self.launcher else "[NATIVE]"
        fav_str = "★ Yes" if self.favorite else "No"
        fav_badge = "★ FAVORITE" if self.favorite else "☆ STANDARD"
        fav_bg = "#eab30826" if self.favorite else "#33415540"
        fav_fg = "#facc15" if self.favorite else "#94a3b8"
        last_str = self.last_played[:19] if self.last_played else "Never"
        date_add_str = (self.date_added or "Recently Added")[:10]
        
        hours = self.playtime_minutes // 60
        mins = self.playtime_minutes % 60
        pt_str = f"{hours}h {mins}m" if hours > 0 else f"{mins}m"
        
        is_wine_env = (self.source or "").lower() in ("steam", "lutris", "heroic", "wine", "filesystem") or (self.launcher or "").lower() in ("wine", "proton", "bottles")
        plat_str = self.platform or ("Windows (Wine/Proton)" if is_wine_env else "Linux Native")
        wine_str = self.wine_version or ("Wine-GE / Proton" if is_wine_env else "N/A")
        ver_str = self.version or "1.0"
        
        exec_str = str(self.executable) if self.executable else "N/A"
        install_str = str(self.install_path) if self.install_path else "N/A"
        tags_str = ", ".join(self.tags) if self.tags else "None"
        colls_str = ", ".join(self.collections) if self.collections else "None"
        
        hero_str = str(self.hero.name) if self.hero else "[Fallback Icon]"
        logo_str = str(self.logo.name) if self.logo else "[Fallback Icon]"
        icon_str = str(self.icon.name) if self.icon else "[Fallback Icon]"

        l_badge = f"<span background='#00e69926' foreground='#00e699' weight='bold'> {launcher_badge} </span>"
        p_badge = f"<span background='#0284c726' foreground='#38bdf8' weight='bold'> [{plat_str.upper()}] </span>"
        w_badge = f"<span background='#a855f726' foreground='#c084fc' weight='bold'> [{wine_str.upper()}] </span>"
        v_badge = f"<span background='#47556940' foreground='#e2e8f0' weight='bold'> [v{ver_str}] </span>"
        f_badge = f"<span background='{fav_bg}' foreground='{fav_fg}' weight='bold'> {fav_badge} </span>"

        art_status = (
            f"<b>Hero:</b> {hero_str}  •  <b>Logo:</b> {logo_str}"
            if self.hero
            else f"<b>Icon:</b> {icon_str}  •  <b>Banner:</b> <span foreground='#00e699'>Gradient Active</span>  •  <b>Hero:</b> {hero_str}  •  <b>Logo:</b> {logo_str}"
        )

        return (
            f"<span font_desc='Outfit Bold 14' size='large' weight='heavy' foreground='#ffffff'><b>Title:</b> {self.title}</span>  {f_badge}  •  "
            f"<b>Launcher:</b> {launcher_badge} {l_badge}  •  <b>Platform:</b> {plat_str} {p_badge}  •  <b>Wine:</b> {wine_str} {w_badge}\n"
            f"<b>Executable:</b> {exec_str}  •  <b>Install Path:</b> {install_str}\n"
            f"<b>Version:</b> {ver_str} {v_badge}  •  <b>Playtime:</b> {pt_str}  •  <b>Last Played:</b> {last_str}  •  <b>Date Added:</b> {date_add_str}\n"
            f"<b>Favorite:</b> {fav_str}  •  <b>Collections:</b> {colls_str}  •  <b>Tags:</b> {tags_str}  •  {art_status}"
        )

    def format_rofi_mesg(self) -> str:
        """Return a rich Pango markup string for Rofi's -mesg status bar or details header.

        Designed to display live game details and premium header below the keyboard hint bar
        or as the prominent game header in dedicated details views.

        Returns:
            A Pango markup string suitable for passing to Rofi ``-mesg``.
        """
        return self.format_header_pango()


def format_rofi_mesg(game: "Game", metadata_cache: Any | None = None) -> str:  # noqa: F821
    """Convenience function: produce a Rofi -mesg rich-text string for a Game.

    Args:
        game: The Game model to format.
        metadata_cache: Optional MetadataCache for looking up dynamic metadata.

    Returns:
        Pango markup string suitable for Rofi ``-mesg``.
    """
    from gamedeck.details import GameDetailsProvider
    provider = GameDetailsProvider(metadata_cache=metadata_cache) if metadata_cache else GameDetailsProvider()
    details = provider.get_details(game)
    if details is not None:
        return details.format_rofi_mesg()
    # Minimal fallback when details cannot be resolved
    launcher_badge = f"[{game.launcher.upper()}]" if game.launcher else "[NATIVE]"
    fav_icon = "★" if game.favorite else "☆"
    return f"<b>{game.name}</b>  {fav_icon}  •  <b>Launcher:</b> {launcher_badge}  •  <b>Launches:</b> {game.launch_count}"



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
