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
from gamedeck.ui.artwork_resolver import ArtworkResolver
from gamedeck.ui.views.cards import CardStyle, get_card_style

logger = logging.getLogger(__name__)

STATUS_BAR_TEXT: str = (
    "<b>Enter</b> Play  •  <b>Alt</b> Options  •  "
    "<b>Ctrl+1</b> List  •  <b>Ctrl+2</b> Grid  •  "
    "<b>Ctrl+F</b> Search  •  <b>Esc</b> Back  •  <b>F5</b> Refresh"
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
class GridViewRenderer:
    """Renders library games in a responsive artwork grid using Rofi."""

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
    font: "Outfit 11";
    accent: {self.accent_color};
    bg-glass: rgba(16, 24, 22, 0.78);
    bg-card: rgba(24, 36, 33, 0.65);
    bg-card-hover: rgba(0, 230, 153, 0.18);
    bg-card-selected: rgba(0, 230, 153, 0.28);
    border-subtle: rgba(0, 230, 153, 0.22);
    fg-main: #f0fdf4;
    fg-muted: #94a3b8;
}}

window {{
    width: 82%;
    border: 2px solid @border-subtle;
    border-radius: 16px;
    background-color: @bg-glass;
    padding: 16px;
}}

mainbox {{
    spacing: 12px;
    children: [ inputbar, message, listview ];
}}

inputbar {{
    background-color: rgba(10, 18, 16, 0.85);
    border: 1px solid @border-subtle;
    border-radius: 10px;
    padding: 10px 14px;
    children: [ prompt, entry ];
}}

prompt {{
    text-color: @accent;
    font: "Outfit Bold 11";
    padding: 0px 8px 0px 0px;
}}

entry {{
    text-color: @fg-main;
    placeholder: "Type to search grid...";
    placeholder-color: @fg-muted;
}}

message {{
    border: 1px solid @border-subtle;
    border-radius: 8px;
    background-color: rgba(12, 20, 18, 0.6);
    padding: 8px 12px;
}}

textbox {{
    text-color: @fg-muted;
}}

listview {{
    columns: {columns};
    lines: {lines_count};
    layout: vertical;
    fixed-columns: true;
    spacing: 12px;
    cycle: true;
    dynamic: true;
    background-color: transparent;
}}

element {{
    orientation: vertical;
    children: [ element-icon, element-text ];
    spacing: 8px;
    padding: 12px;
    border-radius: 12px;
    background-color: @bg-card;
    border: 1px solid rgba(255, 255, 255, 0.05);
}}

element selected {{
    background-color: @bg-card-selected;
    border: 2px solid @accent;
    text-color: #ffffff;
}}

element-icon {{
    size: {icon_size}px;
    horizontal-align: 0.5;
    border-radius: 8px;
    cursor: pointer;
}}

element-text {{
    horizontal-align: 0.5;
    font: "Outfit Medium 10";
    text-color: @fg-main;
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
            card_label = card_style.format_card_label(game)
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
        mesg_parts.append(STATUS_BAR_TEXT)
        full_mesg = "\n".join(mesg_parts)

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
            "-kb-custom-1",
            self.secondary_action_key,
            "-kb-custom-2",
            "Control+1",
            "-kb-custom-3",
            "Control+2",
            "-kb-custom-4",
            "Control+f",
            "-kb-custom-5",
            "F5",
            "-mesg",
            full_mesg,
            "-theme-str",
            grid_theme,
        ]

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
        launcher = game.launcher or "native"
        platform = getattr(game, "platform", None) or "Linux"
        wine_ver = getattr(game, "wine_version", None) or "N/A"
        last_p = getattr(game, "last_played", None) or "Never"
        playtime = getattr(game, "playtime_minutes", 0) or 0
        hours = playtime // 60
        mins = playtime % 60
        pt_str = f"{hours}h {mins}m" if hours > 0 else f"{mins}m"

        return (
            f"<b>{game.name}</b>  •  <b>Source:</b> {source}  •  <b>Launcher:</b> {launcher}  •  "
            f"<b>Platform:</b> {platform}  •  <b>Wine:</b> {wine_ver}  •  "
            f"<b>Playtime:</b> {pt_str}  •  <b>Last Played:</b> {last_p}"
        )
