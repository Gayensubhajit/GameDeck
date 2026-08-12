"""Abstract LibraryView interface and core view contracts for GameDeck.

Defines the pluggable view interface that all presentation modes (List, Grid, Compact,
Hero, Carousel) implement. The rest of GameDeck interacts exclusively with this interface.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path
from typing import Any

import os

from gamedeck.models import Game

__all__ = [
    "LibraryView",
    "ViewMode",
    "get_rofi_env",
]

logger = logging.getLogger(__name__)


def get_rofi_env() -> dict[str, str]:
    """Prepare a robust environment dictionary for executing Rofi across display servers.

    On GNOME Wayland (Mutter), Rofi with Wayland backend crashes because GNOME does not
    implement the zwlr_layer_shell_v1 protocol ('Rofi on wayland requires support for the layer shell protocol').
    When GNOME/Mutter is detected under Wayland and DISPLAY is present (Xwayland),
    we route Rofi to use the X11/Xwayland backend (GDK_BACKEND=x11) so the window opens reliably.
    On wlroots compositors (Hyprland, Sway, etc.), native Wayland is preserved.
    """
    env = dict(os.environ)
    desktop = env.get("XDG_CURRENT_DESKTOP", "").upper()
    session_type = env.get("XDG_SESSION_TYPE", "").lower()

    is_gnome_or_mutter = any(d in desktop for d in ("GNOME", "MUTTER", "PANTHEON", "UNITY"))
    if session_type == "wayland" and is_gnome_or_mutter and env.get("DISPLAY"):
        env.pop("WAYLAND_DISPLAY", None)
        env["GDK_BACKEND"] = "x11"

    return env



class ViewMode(str, Enum):
    """Supported library presentation modes."""

    LIST = "list"
    GRID = "grid"
    DECK = "deck"
    COMPACT = "compact"
    HERO = "hero"
    CAROUSEL = "carousel"


class LibraryView(ABC):
    """Abstract interface for all GameDeck library presentation views.

    All views share:
    - Search tokenization and fuzzy matching
    - Selection and keyboard navigation
    - Category and tag filtering
    - Context Menu (Alt+Return) triggers
    - Metadata and details panel integration
    - Provider and launcher transparency

    Subclasses implement `render()` to present the library in their distinct visual layout.
    """

    name: str = "base"
    display_name: str = "Base View"
    card_style: str = "portrait"

    @abstractmethod
    def render(
        self,
        games: list[Game],
        prompt: str = "GameDeck > Library",
        theme_path: Path | str | None = None,
        theme_str: str | None = None,
        active_game: Game | None = None,
        **kwargs: Any,
    ) -> tuple[Game | Any | None, int, str]:
        """Render the library games and return the selection result.

        Args:
            games: List of games to display.
            prompt: Header prompt / title string.
            theme_path: Optional path to external .rasi theme file.
            theme_str: Optional inline .rasi theme string.
            active_game: Optional game currently focused for live details preview.
            kwargs: Additional view-specific rendering parameters.

        Returns:
            Tuple of (selected_game_or_payload, exit_code, action_trigger):
                - selected_game_or_payload: Selected Game instance, submenu token, or None.
                - exit_code: Process return code (0, 10, 11, 12, etc.).
                - action_trigger: Action name ('launch', 'action_menu', 'switch_view_list',
                  'switch_view_grid', 'switch_view_compact', 'switch_view_hero', 'switch_view_carousel', 'refresh', 'cancel').
        """
        pass
