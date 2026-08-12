"""Hero Panel renderer component for GameDeck.

Renders a read-only Hero Panel showing a large hero image (or graceful fallback),
game logo, title, genre, launcher, platform, playtime, last played, tags,
collections, and quick action hints when a game is selected.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from gamedeck.models import Game
from gamedeck.ui.artwork_resolver import ArtworkResolver

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class HeroPanel:
    """Read-only Hero Panel displaying game artwork, metadata, and quick action hints."""

    artwork_resolver: ArtworkResolver = field(default_factory=ArtworkResolver)

    def render_panel_pango(self, game: Game) -> str:
        """Format a rich, read-only Hero Panel header string for display beside or above the library.

        Displays:
        • Hero Artwork & Logo
        • Large Title
        • Genre Badge
        • Launcher Badge
        • Platform Badge
        • Playtime
        • Last Played
        • Tags
        • Collections
        • Quick Actions
        """
        # 1. Artwork resolution with graceful fallback
        hero_art = self.artwork_resolver.get_hero(game)
        cover_art = self.artwork_resolver.get_cover(game)
        icon_art = self.artwork_resolver.get_icon(game)
        logo_art = getattr(game, "logo", None)

        hero_name = Path(hero_art).name if hero_art else (Path(cover_art).name if cover_art else "")
        logo_name = Path(logo_art).name if logo_art else "[Logo]"
        icon_name = Path(icon_art).name if icon_art else "[Icon]"

        # Graceful artwork status indicator
        if hero_art:
            art_status = f"🖼️ <b>Hero Artwork:</b> <span foreground='#00e699'>{hero_name}</span>  •  ✨ <b>Logo:</b> <span foreground='#38bdf8'>{logo_name}</span>"
        elif cover_art:
            art_status = f"🖼️ <b>Hero Artwork:</b> <span foreground='#00e699'>{hero_name}</span>  •  ✨ <b>Logo:</b> <span foreground='#38bdf8'>{logo_name}</span>"
        else:
            art_status = f"🎮 <b>Icon:</b> <span foreground='#38bdf8'>{icon_name}</span>  •  🎨 <b>Banner:</b> <span foreground='#00e699'>Gradient Glassmorphism Active</span>"

        # 2. Badges
        launcher_raw = (game.launcher or game.source or "native").upper()
        l_badge = f"<span background='#00e69926' foreground='#00e699' weight='bold'> [{launcher_raw}] </span>"

        is_wine = (game.launcher or "").lower() in ("wine", "proton", "bottles") or (game.source or "").lower() == "wine"
        plat_str = getattr(game, "platform", None) or ("Windows (Wine/Proton)" if is_wine else "Linux Native")
        p_badge = f"<span background='#0284c726' foreground='#38bdf8' weight='bold'> [{plat_str.upper()}] </span>"

        fav_badge = "★ FAVORITE" if game.favorite else "☆ STANDARD"
        fav_bg = "#eab30826" if game.favorite else "#33415540"
        fav_fg = "#facc15" if game.favorite else "#94a3b8"
        f_badge = f"<span background='{fav_bg}' foreground='{fav_fg}' weight='bold'> {fav_badge} </span>"

        # 3. Genre, Playtime, Last Played, Tags & Collections
        tags = getattr(game, "tags", None) or []
        collections = getattr(game, "collections", None) or []
        genre_str = getattr(game, "genre", None) or (tags[0] if tags else "Action / Adventure")

        playtime = getattr(game, "playtime_minutes", 0) or 0
        hrs = playtime // 60
        mins = playtime % 60
        pt_str = f"{hrs}h {mins}m" if hrs > 0 else f"{mins}m"

        last_str = game.last_played[:10] if game.last_played else "Never"
        tags_str = ", ".join(tags) if tags else "None"
        colls_str = ", ".join(collections) if collections else "None"

        # Escape XML characters in game title
        safe_name = game.name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        # 4. Read-only Hero Panel formatting lines
        # Line 1: Title + Logo Tag + Favorite Badge
        line1 = f"<span font_desc='Outfit Bold 16' size='x-large' weight='heavy' foreground='#ffffff'><b>{safe_name}</b></span>  {f_badge}"
        # Line 2: Badges row (Genre, Launcher, Platform)
        line2 = f"🎭 <b>Genre:</b> <span foreground='#f8fafc' weight='bold'>{genre_str}</span>  •  <b>Launcher:</b> {l_badge}  •  <b>Platform:</b> {p_badge}"
        # Line 3: Small Metadata (Playtime, Last Played, Tags, Collections)
        line3 = f"<span size='small' foreground='#94a3b8'>⏱ <b>Playtime:</b> <span foreground='#f8fafc' weight='bold'>{pt_str}</span>  •  📅 <b>Last Played:</b> <span foreground='#f8fafc' weight='bold'>{last_str}</span>  •  🏷 <b>Tags:</b> {tags_str}  •  📁 <b>Collections:</b> {colls_str}</span>"
        # Line 4: Quick Actions & Artwork Status (Read-Only)
        line4 = f"<span size='small' foreground='#64748b'>{art_status}  •  ⚡ <b>Quick Actions:</b> [Enter] Play  •  [Alt] Menu  •  [Ctrl+D] Details  •  [Ctrl+F] Search</span>"

        return f"{line1}\n{line2}\n{line3}\n{line4}"
