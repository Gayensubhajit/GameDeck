"""Multi-view presentation subsystem for GameDeck.

Provides modular pluggable view renderers (ListView, GridView, CompactView, HeroView,
CarouselView), seamless view switching via keyboard shortcuts, and active view persistence.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from gamedeck.models import Game
from gamedeck.ui.artwork_resolver import ArtworkResolver
from gamedeck.ui.views.base import LibraryView, ViewMode, get_rofi_env
from gamedeck.ui.views.cards import (
    CARD_STYLES,
    CardStyle,
    CompactCardStyle,
    HeroCardStyle,
    LandscapeCardStyle,
    PortraitCardStyle,
    get_card_style,
)
from gamedeck.ui.views.grid import (
    CarouselView,
    CompactView,
    DeckView,
    GridView,
    GridViewRenderer,
    HeroView,
    calculate_responsive_columns,
)
from gamedeck.ui.views.list import ListView, ListViewRenderer

logger = logging.getLogger(__name__)

__all__ = [
    "LibraryView",
    "ViewMode",
    "get_rofi_env",
    "ViewManager",

    "BaseViewRenderer",
    "ListView",
    "GridView",
    "DeckView",
    "CompactView",
    "HeroView",
    "CarouselView",
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

# Backwards compatibility protocol alias
BaseViewRenderer = LibraryView


class ViewManager:
    """Coordinates pluggable library views, view switching, and active view state.

    The rest of GameDeck does not need to know which view is active; it simply
    calls `view_manager.render(games, ...)` and `ViewManager` delegates directly
    to the active `LibraryView` implementation.
    """

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

        # Registered view catalog
        self._views: dict[str, LibraryView] = {}
        self._register_default_views()

        # Initialize default view mode
        mode_str = str(default_view).lower().replace("viewmode.", "")
        if mode_str not in self._views:
            mode_str = "list"
        self._active_mode = mode_str

        # Load persisted view from DB if available
        if self.db_cache is not None:
            saved_view = self.load_persisted_view()
            if saved_view and saved_view in self._views:
                self._active_mode = saved_view

    def _register_default_views(self) -> None:
        """Register default built-in presentation views."""
        self.register_view(ListView())
        self.register_view(
            GridView(
                columns=self.grid_columns,
                card_style_name=self.grid_card_style,
                artwork_resolver=self.artwork_resolver,
            )
        )
        self.register_view(
            DeckView(
                columns=6,
                artwork_resolver=self.artwork_resolver,
            )
        )
        self.register_view(
            CompactView(
                columns=8,
                artwork_resolver=self.artwork_resolver,
            )
        )
        self.register_view(
            HeroView(
                columns=3,
                artwork_resolver=self.artwork_resolver,
            )
        )
        self.register_view(
            CarouselView(
                columns=4,
                artwork_resolver=self.artwork_resolver,
            )
        )

    def register_view(self, view: LibraryView) -> None:
        """Register a new pluggable LibraryView instance."""
        self._views[view.name.lower()] = view
        logger.debug("Registered LibraryView '%s' (%s)", view.name, view.display_name)

    def register_external_view(self, view: LibraryView) -> None:
        """Register a LibraryView provided by an external plugin.

        Views registered this way are immediately available via ViewManager.switch_to(),
        the --view CLI flag, and all keyboard view-switching shortcuts.

        Args:
            view: A LibraryView instance from a BaseViewPlugin implementation.
        """
        self.register_view(view)
        logger.info("Registered external view plugin: '%s' (%s)", view.name, view.display_name)

    def get_view(self, name: str | ViewMode) -> LibraryView | None:
        """Retrieve a registered LibraryView by name."""
        key = str(name).lower().replace("viewmode.", "")
        return self._views.get(key)

    @property
    def list_renderer(self) -> ListView:
        """Backwards-compatibility property for list renderer."""
        return self._views.get("list")  # type: ignore[return-value]

    @property
    def grid_renderer(self) -> GridView:
        """Backwards-compatibility property for grid renderer."""
        return self._views.get("grid")  # type: ignore[return-value]

    @property
    def active_view(self) -> LibraryView:
        """Get the current active LibraryView instance."""
        return self._views.get(self._active_mode, self._views.get("list"))  # type: ignore[return-value]

    @property
    def active_mode(self) -> ViewMode:
        """Get the current active view mode enum."""
        try:
            return ViewMode(self._active_mode)
        except ValueError:
            return ViewMode.LIST

    @active_mode.setter
    def active_mode(self, mode: ViewMode | str) -> None:
        """Set and persist the active view mode."""
        key = str(mode).lower().replace("viewmode.", "")
        if key in self._views:
            self._active_mode = key
            self.persist_active_view(key)

    def switch_to(self, view_name: str | ViewMode) -> None:
        """Switch current active view to the specified view name."""
        self.active_mode = view_name

    def switch_to_list(self) -> None:
        """Switch current presentation to List View."""
        self.active_mode = "list"

    def switch_to_grid(self) -> None:
        """Switch current presentation to Grid View."""
        self.active_mode = "grid"

    def switch_to_compact(self) -> None:
        """Switch current presentation to Compact View."""
        self.active_mode = "compact"

    def switch_to_hero(self) -> None:
        """Switch current presentation to Hero View."""
        self.active_mode = "hero"

    def switch_to_carousel(self) -> None:
        """Switch current presentation to Carousel View."""
        self.active_mode = "carousel"

    def load_persisted_view(self) -> str | None:
        """Load the saved view preference from SQLite."""
        if self.db_cache is None:
            return None
        try:
            val = self.db_cache.get_ui_state("active_view", None)
            if val and val.lower() in self._views:
                return val.lower()
        except Exception as err:
            logger.debug("Failed to load persisted view: %s", err)
        return None

    def persist_active_view(self, mode: ViewMode | str) -> None:
        """Save the active view preference to SQLite."""
        if self.db_cache is None:
            return
        try:
            val = str(mode).lower().replace("viewmode.", "")
            self.db_cache.set_ui_state("active_view", val)
        except Exception as err:
            logger.debug("Failed to persist active view: %s", err)

    def render(
        self,
        games: list[Game],
        prompt: str = "GameDeck > Library",
        theme_path: Path | str | None = None,
        theme_str: str | None = None,
        active_game: Game | None = None,
        **kwargs: Any,
    ) -> tuple[Game | Any | None, int, str]:
        """Delegate rendering to the active LibraryView instance."""
        view = self.active_view
        return view.render(
            games=games,
            prompt=prompt,
            theme_path=theme_path,
            theme_str=theme_str,
            active_game=active_game,
            **kwargs,
        )
