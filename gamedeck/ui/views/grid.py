"""GridViewRenderer: Card-based grid presentation for GameDeck.

Renders library games as compact, modern artwork cards in responsive rows
with frosted-glass visual styling, green accent focus, dynamic column scaling,
multi-tier artwork resolution, and instant keyboard navigation.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gamedeck.models import Game
from gamedeck.search.tokenizer import tokenize as _search_tokenize
from gamedeck.ui.artwork_resolver import ArtworkResolver
from gamedeck.ui.views.base import LibraryView
from gamedeck.ui.views.cards import CardStyle, get_card_style

logger = logging.getLogger(__name__)

STATUS_BAR_TEXT: str = (
    "<b>⏎ Enter</b> Play  •  <b>⎇ Alt</b> Menu  •  "
    "<b>Ctrl+1</b> List  •  <b>Ctrl+2</b> Grid  •  <b>Ctrl+3</b> Hero  •  <b>Ctrl+4</b> Compact  •  "
    "<b>Ctrl+D</b> Details  •  <b>Ctrl+F</b> Search  •  <b>⎋ Esc</b> Back  •  <b>F5</b> Refresh"
)


def calculate_responsive_columns(
    total_games: int,
    configured_columns: int = 0,
    window_width: int | None = None,
) -> int:
    """Determine dynamic column count adapted to screen resolution and window width.

    Small screens (< 1200px): 3 columns
    Medium screens (1200px - 1800px): 5 columns
    Large screens (> 1800px): 6–8 columns
    """
    if configured_columns > 0:
        return max(1, min(configured_columns, 12))

    # Detect display width if available via environment or tools
    width = window_width or 1600
    try:
        if "COLUMNS" in os.environ:
            term_cols = int(os.environ["COLUMNS"])
            if term_cols < 100:
                width = 1000
            elif term_cols > 200:
                width = 2200
    except Exception:
        pass

    if width < 1200 or total_games <= 6:
        return 3
    elif width < 1800:
        return 5
    elif width < 2500:
        return 6
    else:
        return 8


@dataclass(slots=True)
class GridView(LibraryView):
    """Renders library games in a responsive portrait artwork grid using Rofi."""

    name: str = "grid"
    display_name: str = "Grid View"
    card_style: str = "portrait"
    columns: int = 5
    card_style_name: str = "portrait"
    artwork_resolver: ArtworkResolver = field(default_factory=ArtworkResolver)
    rofi_bin: str = "rofi"
    accent_color: str = "#00e699"
    secondary_action_key: str = "Alt+Return"

    def get_card_style(self) -> CardStyle:
        """Get the active CardStyle instance."""
        return get_card_style(self.card_style_name)

    def generate_grid_theme_str(
        self,
        columns: int,
        card_style: CardStyle,
        custom_theme_str: str | None = None,
    ) -> str:
        """Generate frosted-glass RASI theme tokens for grid layout."""
        icon_size = card_style.icon_size_px
        lines_count = max(2, min(4, 3))

        base_rasi = f"""
* {{
    background-color: transparent;
    text-color: #e2e8f0;
    font: "Outfit 11";
    accent: {self.accent_color};
}}

window {{
    width: 84%;
    location: center;
    anchor: center;
    border: 1.5px solid;
    border-color: #00e69944;
    border-radius: 18px;
    background-color: #0c1412f4;
    padding: 20px;
}}

mainbox {{
    spacing: 14px;
    children: [ inputbar, message, listview ];
    background-color: transparent;
}}

inputbar {{
    background-color: #14201ce0;
    border: 1px solid;
    border-color: #00e69944;
    border-radius: 12px;
    padding: 10px 16px;
    spacing: 12px;
    children: [ prompt, entry ];
}}

prompt {{
    text-color: #00e699;
    font: "Outfit Bold 11";
    background-color: transparent;
}}

entry {{
    text-color: #f0fdf4;
    font: "Outfit Regular 11";
    placeholder: "Type to search grid (title, tags, launcher)...";
    placeholder-color: #64748b;
    background-color: transparent;
}}

message {{
    background-color: #14201cc8;
    border: 1px solid;
    border-color: #00e69933;
    border-radius: 12px;
    padding: 10px 16px;
}}

textbox {{
    text-color: #94a3b8;
    font: "Outfit Regular 9.5";
    background-color: transparent;
}}

listview {{
    columns: {columns};
    lines: {lines_count};
    layout: vertical;
    fixed-columns: true;
    spacing: 14px;
    cycle: true;
    dynamic: true;
    scrollbar: false;
    background-color: transparent;
}}

element {{
    orientation: vertical;
    children: [ element-icon, element-text ];
    spacing: 8px;
    padding: 12px;
    border-radius: 14px;
    background-color: #14201ca6;
    border: 1px solid;
    border-color: #24383280;
    text-color: #cbd5e1;
}}

element selected {{
    background-color: #00e69926;
    border: 2px solid;
    border-color: #00e699;
    text-color: #00e699;
}}

element-icon {{
    size: {icon_size}px;
    horizontal-align: 0.5;
    vertical-align: 0.5;
    border-radius: 8px;
    background-color: transparent;
    cursor: pointer;
}}

element-text {{
    horizontal-align: 0.5;
    vertical-align: 0.5;
    font: "Outfit SemiBold 10";
    text-color: inherit;
    background-color: transparent;
    cursor: pointer;
}}
"""
        if custom_theme_str and custom_theme_str.strip():
            return f"{base_rasi}\n{custom_theme_str.strip()}"
        return base_rasi

    def render(
        self,
        games: list[Game],
        prompt: str = "GameDeck > Grid",
        active_game: Game | None = None,
        theme_path: Path | str | None = None,
        theme_str: str | None = None,
        **kwargs: Any,
    ) -> tuple[Game | Any | None, int, str]:
        """Display games as artwork cards in the Grid View.

        Returns:
            (selected_item, return_code, action_trigger)
            return_code 0: Enter (launch / select)
            return_code 10: Alt+Return (context action menu)
            return_code 11: Ctrl+1 (switch to List View)
            return_code 12: Ctrl+2 (stay in / refresh Grid View)
            return_code 13: Ctrl+F (search)
            return_code 14: F5 (refresh library)
        """
        if not games:
            return (None, 1, "cancel")

        card_style = self.get_card_style()
        cols = calculate_responsive_columns(len(games), self.columns)
        grid_theme = self.generate_grid_theme_str(cols, card_style, theme_str)

        lines: list[str] = []
        name_map: dict[str, Game] = {}

        # Import tokenizer for instant search keywords
        from gamedeck.search.tokenizer import tokenize as _search_tokenize

        for idx, game in enumerate(games):
            card_label = card_style.format_card_label(
                game, playtime_minutes=getattr(game, "playtime_minutes", 0)
            )
            name_map[card_label] = game

            # Multi-tier artwork resolution
            cover_art = self.artwork_resolver.resolve_grid_cover(
                game, preferred_type=card_style.preferred_artwork
            )

            # Build rich search tokens
            tags = getattr(game, "tags", None)
            collections = getattr(game, "collections", None)
            tokens = set(_search_tokenize(
                name=game.name,
                appid=game.appid,
                source=game.source,
                launcher=game.launcher,
                executable=game.executable,
                tags=tags,
                collections=collections,
            ))
            if game.favorite:
                tokens.update(["favorite", "favorites", "star", "starred"])
            if game.installed:
                tokens.add("installed")
            meta_str = " ".join(sorted(tokens))

            parts = [card_label, f"info\x1fgame:{idx}", f"meta\x1f{meta_str}"]
            if cover_art:
                parts.insert(1, f"icon\x1f{cover_art}")

            lines.append(f"{parts[0]}\0{'\x1f'.join(parts[1:])}")

        executable = shutil.which(self.rofi_bin)
        if executable is None:
            raise RuntimeError(f"Rofi executable '{self.rofi_bin}' was not found.")

        # Build details panel message header if active_game is provided, plus persistent status bar
        mesg_parts: list[str] = []
        if active_game is not None:
            mesg_parts.append(self._build_details_panel(active_game))
        custom_status = kwargs.get("status_bar") or STATUS_BAR_TEXT
        mesg_parts.append(custom_status)
        full_mesg = "\n".join(mesg_parts)

        # Write grid theme to cache file for clean and reliable Rofi parsing
        cache_dir = Path.home() / ".cache" / "gamedeck"
        cache_dir.mkdir(parents=True, exist_ok=True)
        theme_file = cache_dir / "grid_theme.rasi"
        try:
            theme_file.write_text(grid_theme, encoding="utf-8")
        except Exception as err:
            logger.debug("Failed to write grid theme cache: %s", err)

        cmd: list[str] = [
            executable,
            "-dmenu",
            "-p",
            prompt,
            "-format",
            "i",
            "-show-icons",
            "-i",
            "-sort",
            "-sorting-method",
            "fzf",
        ]

        if self.secondary_action_key:
            cmd.extend(["-kb-custom-1", self.secondary_action_key])
        cmd.extend([
            "-kb-remove-char-forward", "Delete",
            "-kb-custom-2", "Control+1",
            "-kb-custom-3", "Control+2",
            "-kb-custom-4", "F5",
            "-kb-custom-5", "Control+d",
            "-kb-custom-6", "Control+3",
            "-kb-custom-7", "Control+4",
            "-mesg", full_mesg,
            "-theme", str(theme_file),
        ])

        if theme_path:
            cmd.extend(["-theme", str(theme_path)])

        input_payload = "\n".join(lines) + "\n"

        try:
            result = subprocess.run(
                cmd,
                input=input_payload,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except OSError as err:
            logger.error("Failed to execute Rofi grid process: %s", err)
            raise RuntimeError(f"Failed to execute Rofi grid: {err}") from err

        ret_code = result.returncode
        output = result.stdout.strip()

        # Handle keyboard shortcut return codes
        if ret_code == 11:
            return (None, 11, "switch_view_list")
        elif ret_code == 12:
            return (None, 12, "switch_view_grid")
        elif ret_code == 14:
            return (None, 14, "refresh")
        elif ret_code == 15:
            # Ctrl+D — details overlay; return special trigger for caller to handle
            if output.isdigit():
                idx = int(output)
                if 0 <= idx < len(games):
                    return (games[idx], 15, "show_details")
            return (None, 15, "show_details")
        elif ret_code == 16:
            return (None, 16, "switch_view_hero")
        elif ret_code == 17:
            return (None, 17, "switch_view_compact")
        elif ret_code not in (0, 10):
            return (None, ret_code, "cancel")

        if not output:
            return (None, ret_code, "cancel")

        is_secondary = (ret_code == 10)
        action_trigger = "action_menu" if is_secondary else "launch"

        if output.isdigit():
            idx = int(output)
            if 0 <= idx < len(games):
                return (games[idx], ret_code, action_trigger)

        selected_game = name_map.get(output)
        if selected_game:
            return (selected_game, ret_code, action_trigger)

        return (None, ret_code, "cancel")

    def _build_details_panel(self, game: Game) -> str:
        """Format a rich details panel string for the selected game."""
        source = (game.source or "unknown").capitalize()
        launcher = (game.launcher or "native").upper()
        platform = getattr(game, "platform", None) or "Linux Native"
        wine_ver = getattr(game, "wine_version", None) or "N/A"
        last_p = getattr(game, "last_played", None) or "Never"
        date_add_str = (getattr(game, "date_added", None) or "Recently Added")[:10]
        playtime = getattr(game, "playtime_minutes", 0) or 0
        hours = playtime // 60
        mins = playtime % 60
        pt_str = f"{hours}h {mins}m" if hours > 0 else f"{mins}m"
        fav_str = "★ Yes" if game.favorite else "No"
        ver_str = getattr(game, "version", None) or "1.0"
        exe_path = str(game.executable) if game.executable else "N/A"
        install_dir = str(Path(game.executable).parent) if game.executable else "N/A"
        tags_str = ", ".join(game.tags) if getattr(game, "tags", None) else "None"
        colls_str = ", ".join(game.collections) if getattr(game, "collections", None) else "None"

        hero_art = self.artwork_resolver.get_hero(game)
        logo_art = getattr(game, "logo", None)
        cover_art = self.artwork_resolver.get_cover(game)
        hero_str = Path(hero_art).name if hero_art else (Path(cover_art).name if cover_art else "[Fallback Icon]")
        logo_str = Path(logo_art).name if logo_art else "[Fallback Icon]"

        return (
            f"<b>Title:</b> {game.name}  •  <b>Launcher:</b> [{launcher}]  •  <b>Source:</b> {source}  •  <b>Platform:</b> {platform}\n"
            f"<b>Executable:</b> {exe_path}  •  <b>Install Path:</b> {install_dir}\n"
            f"<b>Wine:</b> {wine_ver}  •  <b>Playtime:</b> {pt_str}  •  <b>Last Played:</b> {last_p}  •  <b>Date Added:</b> {date_add_str}\n"
            f"<b>Favorite:</b> {fav_str}  •  <b>Version:</b> {ver_str}  •  <b>Collections:</b> {colls_str}  •  <b>Tags:</b> {tags_str}  •  <b>Hero:</b> {hero_str}  •  <b>Logo:</b> {logo_str}"
        )


# Backwards compatibility alias
GridViewRenderer = GridView


@dataclass(slots=True)
class CompactView(LibraryView):
    """Renders library games in a dense square grid (6–8 columns) for maximum information density."""

    name: str = "compact"
    display_name: str = "Compact View"
    card_style: str = "compact"
    columns: int = 7
    card_style_name: str = "compact"
    artwork_resolver: ArtworkResolver = field(default_factory=ArtworkResolver)
    rofi_bin: str = "rofi"
    accent_color: str = "#00e699"
    secondary_action_key: str = "Alt+Return"

    def render(self, *args: Any, **kwargs: Any) -> tuple[Game | Any | None, int, str]:
        renderer = GridView(
            columns=self.columns,
            card_style_name=self.card_style_name,
            artwork_resolver=self.artwork_resolver,
            rofi_bin=self.rofi_bin,
            accent_color=self.accent_color,
            secondary_action_key=self.secondary_action_key,
        )
        return renderer.render(*args, **kwargs)


@dataclass(slots=True)
class HeroView(LibraryView):
    """Renders library games in wide cinematic 21:9 hero banner cards (2–3 columns)."""

    name: str = "hero"
    display_name: str = "Hero View"
    card_style: str = "hero"
    columns: int = 3
    card_style_name: str = "hero"
    artwork_resolver: ArtworkResolver = field(default_factory=ArtworkResolver)
    rofi_bin: str = "rofi"
    accent_color: str = "#00e699"
    secondary_action_key: str = "Alt+Return"

    def render(self, *args: Any, **kwargs: Any) -> tuple[Game | Any | None, int, str]:
        renderer = GridView(
            columns=self.columns,
            card_style_name=self.card_style_name,
            artwork_resolver=self.artwork_resolver,
            rofi_bin=self.rofi_bin,
            accent_color=self.accent_color,
            secondary_action_key=self.secondary_action_key,
        )
        return renderer.render(*args, **kwargs)


@dataclass(slots=True)
class CarouselView(LibraryView):
    """Renders library games in horizontal 16:9 spotlight showcase cards."""

    name: str = "carousel"
    display_name: str = "Carousel View"
    card_style: str = "carousel"
    columns: int = 4
    card_style_name: str = "carousel"
    artwork_resolver: ArtworkResolver = field(default_factory=ArtworkResolver)
    rofi_bin: str = "rofi"
    accent_color: str = "#00e699"
    secondary_action_key: str = "Alt+Return"

    def render(self, *args: Any, **kwargs: Any) -> tuple[Game | Any | None, int, str]:
        renderer = GridView(
            columns=self.columns,
            card_style_name=self.card_style_name,
            artwork_resolver=self.artwork_resolver,
            rofi_bin=self.rofi_bin,
            accent_color=self.accent_color,
            secondary_action_key=self.secondary_action_key,
        )
        return renderer.render(*args, **kwargs)


@dataclass(slots=True)
class DeckView(LibraryView):
    """Console Deck style view matching handheld console UI with top tabs, big cover art, and gamepad actions."""

    name: str = "deck"
    display_name: str = "Deck View"
    card_style: str = "deck"
    columns: int = 6
    card_style_name: str = "deck"
    artwork_resolver: ArtworkResolver = field(default_factory=ArtworkResolver)
    rofi_bin: str = "rofi"
    accent_color: str = "#3b82f6"
    secondary_action_key: str = "Alt+Return"

    def render(self, *args: Any, **kwargs: Any) -> tuple[Game | Any | None, int, str]:
        deck_theme = """
* {
    background-color: transparent;
    text-color: #f1f5f9;
    font: "Outfit 11";
    accent: #3b82f6;
}

window {
    width: 95%;
    location: center;
    anchor: center;
    border: 1.5px solid;
    border-color: #2563eb66;
    border-radius: 20px;
    background-color: #030612fa;
    padding: 18px 24px;
}

mainbox {
    spacing: 16px;
    children: [ inputbar, listview, message ];
    background-color: transparent;
}

inputbar {
    background-color: #080f24d0;
    border: 1px solid;
    border-color: #2563eb44;
    border-radius: 14px;
    padding: 10px 20px;
    spacing: 16px;
    children: [ prompt, entry ];
}

prompt {
    text-color: #60a5fa;
    font: "Outfit Bold 12";
    background-color: transparent;
}

entry {
    text-color: #ffffff;
    font: "Outfit Regular 11";
    placeholder: "Search library...";
    placeholder-color: #64748b;
    background-color: transparent;
}

message {
    background-color: #080f24c0;
    border: 1px solid;
    border-color: #2563eb33;
    border-radius: 12px;
    padding: 8px 18px;
}

textbox {
    text-color: #cbd5e1;
    font: "Outfit Medium 10";
    background-color: transparent;
}

listview {
    columns: 6;
    lines: 2;
    layout: vertical;
    fixed-columns: true;
    spacing: 16px;
    cycle: true;
    dynamic: true;
    scrollbar: false;
    background-color: transparent;
}

element {
    orientation: vertical;
    children: [ element-icon, element-text ];
    spacing: 4px;
    padding: 4px;
    border-radius: 14px;
    background-color: #0c142ba0;
    border: 1.5px solid;
    border-color: #1e293b80;
    text-color: #f8fafc;
}

element selected {
    background-color: #1d4ed830;
    border: 2.5px solid;
    border-color: #3b82f6;
    text-color: #60a5fa;
}

element-icon {
    size: 190px;
    horizontal-align: 0.5;
    vertical-align: 0.5;
    border-radius: 10px;
    background-color: transparent;
    cursor: pointer;
}

element-text {
    horizontal-align: 0.5;
    vertical-align: 0.5;
    font: "Outfit Bold 11";
    text-color: inherit;
    background-color: transparent;
    padding: 6px 6px 8px 6px;
    cursor: pointer;
}
"""
        renderer = GridView(
            columns=self.columns,
            card_style_name=self.card_style_name,
            artwork_resolver=self.artwork_resolver,
            rofi_bin=self.rofi_bin,
            accent_color=self.accent_color,
            secondary_action_key=self.secondary_action_key,
        )
        kwargs_copy = dict(kwargs)
        # Always use the signature console top tabs and gamepad controller hints
        kwargs_copy["prompt"] = "( L1 )   FAVORITES   •   COLLECTION   •   ACCESSORIES   ( R1 )"
        kwargs_copy["status_bar"] = "<b>GAMEDECK</b>                                                                            <b>🎮 NAVIGATE</b>    <b>(X) OPTIONS</b>    <b>(Y) RANDOM PLAY</b>    <b>(A) PLAY</b>"
        if not kwargs_copy.get("theme_str"):
            kwargs_copy["theme_str"] = deck_theme

        return renderer.render(*args, **kwargs_copy)
