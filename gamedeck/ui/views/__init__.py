"""Multi-view presentation subsystem for GameDeck.

Provides modular view renderers (List View, Grid View, Carousel View),
view switching via keyboard shortcuts (Ctrl+1, Ctrl+2), and active view persistence.
"""

from __future__ import annotations

import logging
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from gamedeck.models import Game
from gamedeck.ui.artwork_resolver import ArtworkResolver
from gamedeck.ui.views.cards import (
    CARD_STYLES,
    CardStyle,
    CompactCardStyle,
    HeroCardStyle,
    LandscapeCardStyle,
    PortraitCardStyle,
    get_card_style,
)
from gamedeck.ui.views.grid import GridViewRenderer, calculate_responsive_columns
from gamedeck.ui.views.list import ListViewRenderer

logger = logging.getLogger(__name__)

__all__ = [
    "ViewMode",
    "ViewManager",
    "BaseViewRenderer",
    "GridViewRenderer",
    "ListViewRenderer",
    "CardStyle",
    "PortraitCardStyle",
    "CompactCardStyle",
    "LandscapeCardStyle",
    "HeroCardStyle",
    "get_card_style",
    "calculate_responsive_columns",
]


class ViewMode(str, Enum):
    """Available library presentation modes."""

    LIST = "list"
    GRID = "grid"
    CAROUSEL = "carousel"


class BaseViewRenderer(Protocol):
    """Abstract protocol for GameDeck UI presentation renderers."""

    def render(
        self,
        games: list[Game],
        prompt: str = "GameDeck > Library",
        theme_path: Path | str | None = None,
        theme_str: str | None = None,
        **kwargs: Any,
    ) -> tuple[Game | Any | None, int, str]:
        """Render the library games and return selection with trigger."""
        ...


class ViewManager:
    """Coordinates view renderers, view switching, and active view state."""

    def __init__(
        self,
        default_view: str | ViewMode = ViewMode.LIST,
        grid_columns: int = 5,
        grid_card_style: str = "portrait",
        artwork_resolver: ArtworkResolver | None = None,
        db_cache: Any = None,
    ) -> None:
        self.db_cache = db_cache
        self.artwork_resolver = artwork_resolver or ArtworkResolver()
        self.grid_columns = grid_columns
        self.grid_card_style = grid_card_style

        # Initialize default view mode
        mode_str = str(default_view).lower().replace("viewmode.", "")
        try:
            self._active_mode = ViewMode(mode_str)
        except ValueError:
            self._active_mode = ViewMode.LIST

        # Load persisted view from DB if available
        if self.db_cache is not None:
            saved_view = self.load_persisted_view()
            if saved_view:
                self._active_mode = saved_view

        # Initialize renderers
        self.list_renderer = ListViewRenderer()
        self.grid_renderer = GridViewRenderer(
            columns=self.grid_columns,
            card_style_name=self.grid_card_style,
            artwork_resolver=self.artwork_resolver,
        )

    @property
    def active_mode(self) -> ViewMode:
        """Get the current active view mode."""
        return self._active_mode

    @active_mode.setter
    def active_mode(self, mode: ViewMode | str) -> None:
        """Set and persist the active view mode."""
        if isinstance(mode, str):
            mode = ViewMode(mode.lower())
        self._active_mode = mode
        self.persist_active_view(mode)

    def switch_to_list(self) -> None:
        """Switch current presentation to List View."""
        self.active_mode = ViewMode.LIST

    def switch_to_grid(self) -> None:
        """Switch current presentation to Grid View."""
        self.active_mode = ViewMode.GRID

    def load_persisted_view(self) -> ViewMode | None:
        """Load the saved view preference from SQLite."""
        if self.db_cache is None:
            return None
        try:
            val = self.db_cache.get_ui_state("active_view", None)
            if val in (ViewMode.LIST.value, ViewMode.GRID.value, ViewMode.CAROUSEL.value):
                return ViewMode(val)
        except Exception as err:
            logger.debug("Failed to load persisted view: %s", err)
        return None

    def persist_active_view(self, mode: ViewMode) -> None:
        """Save the active view preference to SQLite."""
        if self.db_cache is None:
            return
        try:
            self.db_cache.set_ui_state("active_view", mode.value)
        except Exception as err:
            logger.debug("Failed to persist active view: %s", err)

    def render(
        self,
        games: list[Game],
        prompt: str = "GameDeck > Library",
        active_game: Game | None = None,
        theme_path: Path | str | None = None,
        theme_str: str | None = None,
        resolve_icon_fn: Any = None,
    ) -> tuple[Game | Any | None, int, str]:
        """Dispatch rendering to the active view renderer."""
        if self._active_mode == ViewMode.GRID:
            return self.grid_renderer.render(
                games=games,
                prompt=prompt,
                active_game=active_game,
                theme_path=theme_path,
                theme_str=theme_str,
            )
        else:
            return self.list_renderer.render(
                games=games,
                prompt=prompt,
                theme_path=theme_path,
                theme_str=theme_str,
                resolve_icon_fn=resolve_icon_fn,
            )
