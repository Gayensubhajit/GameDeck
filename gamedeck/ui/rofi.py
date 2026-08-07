"""Rofi frontend user interface for GameDeck."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from gamedeck.models import Game

__all__ = ["RofiUI", "show_menu", "select_game"]

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RofiUI:
    """Rofi dmenu-based graphical launcher interface for selecting games.

    Presents a searchable, interactive menu of games with optional icons and
    metadata formatting, returning the chosen Game object without launching it.

    Attributes:
        prompt: Display prompt text shown in the Rofi search bar.
        theme: Optional path to a custom Rofi .rasi theme file.
        theme_str: Optional inline .rasi theme string to customize styling.
        show_icons: Whether to enable and send icon paths to Rofi.
        case_insensitive: Whether search matching should be case-insensitive.
        rofi_bin: Name or absolute path of the Rofi executable.
    """

    prompt: str = "GameDeck"
    theme: Path | str | None = None
    theme_str: str | None = None
    show_icons: bool = True
    case_insensitive: bool = True
    rofi_bin: str = "rofi"

    def select(self, games: list[Game]) -> Game | None:
        """Display the list of games in Rofi and return the user's selected Game.

        Args:
            games: List of Game model instances to present.

        Returns:
            The selected Game model instance, or None if the menu was dismissed/cancelled.

        Raises:
            RuntimeError: If the Rofi executable is not installed or not found in PATH.
        """
        if not games:
            return None

        # Verify that rofi executable is available
        executable = shutil.which(self.rofi_bin)
        if executable is None:
            raise RuntimeError(
                f"Rofi executable '{self.rofi_bin}' was not found in PATH. "
                "Please install Rofi or Rofi-Wayland to use the GameDeck UI."
            )

        # Construct Rofi command-line arguments
        cmd: list[str] = [
            executable,
            "-dmenu",
            "-p",
            self.prompt,
            "-format",
            "i",
            "-no-custom",
        ]

        if self.case_insensitive:
            cmd.append("-i")

        if self.show_icons:
            cmd.append("-show-icons")

        if self.theme is not None:
            cmd.extend(["-theme", str(self.theme)])

        if self.theme_str is not None and self.theme_str.strip():
            cmd.extend(["-theme-str", self.theme_str.strip()])

        # Build input payload for Rofi dmenu with icon and info tags
        lines: list[str] = []
        name_map: dict[str, Game] = {}

        for idx, game in enumerate(games):
            display_title = game.name.strip() if game.name else f"Game #{idx + 1}"
            name_map[display_title] = game

            # Determine icon path if available
            icon_path: Path | None = game.icon or game.cover

            if self.show_icons and icon_path is not None and icon_path.exists():
                # Rofi dmenu extended syntax: title\0icon\x1fpath\x1finfo\x1findex
                line = f"{display_title}\0icon\x1f{icon_path}\x1finfo\x1f{idx}"
            else:
                line = f"{display_title}\0info\x1f{idx}"

            lines.append(line)

        input_payload = "\n".join(lines) + "\n"
        logger.debug("Opening Rofi menu with %d items", len(games))

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
            logger.error("Failed to execute Rofi process: %s", err)
            raise RuntimeError(f"Failed to execute Rofi: {err}") from err

        # Return code 0 indicates normal selection; non-zero (e.g. 1, 130) indicates cancel/Escape
        if result.returncode != 0:
            logger.debug("Rofi selection cancelled (returncode=%d)", result.returncode)
            return None

        output = result.stdout.strip()
        if not output:
            return None

        # Parse selected index
        if output.isdigit():
            selected_idx = int(output)
            if 0 <= selected_idx < len(games):
                selected = games[selected_idx]
                logger.info("User selected game: %s [%s]", selected.name, selected.id)
                return selected

        # Fallback to display title matching
        selected = name_map.get(output)
        if selected is not None:
            logger.info("User selected game (title match): %s [%s]", selected.name, selected.id)
        return selected

    def show(self, games: list[Game]) -> Game | None:
        """Alias for select."""
        return self.select(games)


def show_menu(
    games: list[Game],
    prompt: str = "GameDeck",
    theme: Path | str | None = None,
    theme_str: str | None = None,
    show_icons: bool = True,
) -> Game | None:
    """Display a Rofi game selection menu and return the chosen Game.

    Args:
        games: List of Game instances to present in the menu.
        prompt: Title or prompt text to display.
        theme: Optional path to a custom .rasi theme file.
        theme_str: Optional inline .rasi theme string.
        show_icons: Whether to render game cover/icon graphics.

    Returns:
        The selected Game instance, or None if dismissed.
    """
    ui = RofiUI(
        prompt=prompt,
        theme=theme,
        theme_str=theme_str,
        show_icons=show_icons,
    )
    return ui.select(games)


def select_game(
    games: list[Game],
    prompt: str = "GameDeck",
    theme: Path | str | None = None,
    theme_str: str | None = None,
    show_icons: bool = True,
) -> Game | None:
    """Convenience alias to show a Rofi game selection menu."""
    return show_menu(
        games=games,
        prompt=prompt,
        theme=theme,
        theme_str=theme_str,
        show_icons=show_icons,
    )
