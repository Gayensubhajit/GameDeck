"""Extensible dynamic Game Actions system for GameDeck."""

from __future__ import annotations

import importlib
import logging
import os
import pkgutil
import shutil
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from gamedeck.models import Game

__all__ = [
    "GameAction",
    "BaseActionProvider",
    "ActionRegistry",
    "SteamActionProvider",
    "LutrisActionProvider",
    "HeroicActionProvider",
    "NativeActionProvider",
    "FilesystemActionProvider",
    "get_actions_for_game",
    "execute_action",
]

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class GameAction:
    """Represents a discrete executable action for a game.

    Attributes:
        id: Unique identifier for the action (e.g., 'play', 'browse_files', 'open_steam_page').
        label: Human-readable action label for UI display (e.g., 'Play Game', 'Browse Files').
        handler: Callable executing the action given the Game model.
        icon: Optional icon or glyph symbol (e.g. '▶', '📁', '⚙', '🌐').
        description: Brief description of the action.
        is_primary: Whether this is the default primary launch action.
    """

    id: str
    label: str
    handler: Callable[[Game], Any]
    icon: str = ""
    description: str = ""
    is_primary: bool = False

    def execute(self, game: Game) -> Any:
        """Execute the action handler on the given game."""
        return self.handler(game)

    @property
    def display_text(self) -> str:
        """Formatted text with icon for UI menus."""
        if self.icon:
            return f"{self.icon}  {self.label}"
        return self.label


class BaseActionProvider(ABC):
    """Abstract base class for extensible Game Action providers.

    Subclasses dynamically register available actions for games matching their
    source/launcher without hardcoding fixed action lists in UI components.
    """

    #: Source or launcher keys this provider handles (e.g. ('steam',), ('lutris',)).
    sources: tuple[str, ...] = ()

    @abstractmethod
    def get_actions(self, game: Game) -> list[GameAction]:
        """Return all available GameActions for the given game.

        Args:
            game: Game model instance.

        Returns:
            List of valid GameAction instances.
        """

    def is_applicable(self, game: Game) -> bool:
        """Check if this provider applies to the given game."""
        source = (game.source or "").lower().strip()
        launcher = (game.launcher or "").lower().strip()
        return any(s in (source, launcher) for s in self.sources)


# -----------------------------------------------------------------------------
# Common Utility Handlers
# -----------------------------------------------------------------------------


def _open_folder(path: Path | None) -> subprocess.Popen[Any] | None:
    """Open a folder in the user's default desktop file manager."""
    if path is None:
        return None

    folder = path if path.is_dir() else path.parent
    if not folder.exists():
        logger.warning("Target folder does not exist: %s", folder)
        return None

    # Check xdg-open first, fallback to standard Linux file managers
    opener = shutil.which("xdg-open")
    if opener:
        return subprocess.Popen([opener, str(folder)])

    for fm in ("dolphin", "nautilus", "thunar", "pcmanfm", "nemo"):
        bin_path = shutil.which(fm)
        if bin_path:
            return subprocess.Popen([bin_path, str(folder)])

    return None


def _open_url(url: str) -> subprocess.Popen[Any] | None:
    """Open a URL via xdg-open or system browser."""
    opener = shutil.which("xdg-open")
    if opener:
        return subprocess.Popen([opener, url])
    return None


def _open_text_file(path: Path | None) -> subprocess.Popen[Any] | None:
    """Open a text or desktop file in the default desktop editor/viewer."""
    if path is None or not path.exists():
        return None

    opener = shutil.which("xdg-open")
    if opener:
        return subprocess.Popen([opener, str(path)])
    return None


def _remove_game_from_library(game: Game) -> None:
    """Remove a filesystem game record from the local SQLite cache."""
    from gamedeck.database import MetadataCache

    cache = MetadataCache()
    with cache._get_connection() as conn:
        conn.execute("DELETE FROM cached_games WHERE id = ?", (game.id,))
        conn.execute("DELETE FROM game_metadata WHERE id = ?", (game.id,))
    logger.info("Removed game '%s' [%s] from local library cache.", game.name, game.id)


# -----------------------------------------------------------------------------
# Dynamic Provider Handlers
# -----------------------------------------------------------------------------


@dataclass(slots=True)
class UniversalActionProvider(BaseActionProvider):
    """Dynamic action provider that supplies universal context actions for every game."""

    sources: tuple[str, ...] = ("steam", "lutris", "heroic", "native", "filesystem", "wine")

    def is_applicable(self, game: Game) -> bool:
        return True

    def get_actions(self, game: Game) -> list[GameAction]:
        actions: list[GameAction] = []

        # Favorite toggle
        fav_label = "Unfavorite" if game.favorite else "Favorite"
        fav_icon = "⭐" if not game.favorite else "★"
        actions.append(
            GameAction(
                id="toggle_favorite",
                label=fav_label,
                handler=lambda g: None,  # handled via MetadataManager in app loop
                icon=fav_icon,
                description="Toggle favorite pinned status",
            )
        )

        # Open Folder (if executable or install directory exists)
        if game.executable is not None:
            actions.append(
                GameAction(
                    id="open_folder",
                    label="Open Folder",
                    handler=lambda g: _open_folder(Path(g.executable) if g.executable else None),
                    icon="📂",
                    description="Open game directory in desktop file manager",
                )
            )

        # Switch Launch Profile
        actions.append(
            GameAction(
                id="select_profile",
                label="Launch Profiles",
                handler=lambda g: None,  # handled via ProfileManager in UI
                icon="⚡",
                description="Select or switch runtime launcher profile (Lutris, Wine, Steam, Proton Experimental)",
            )
        )

        # Edit Tags
        actions.append(
            GameAction(
                id="edit_tags",
                label="Edit Tags",
                handler=lambda g: None,  # handled via TagManager in UI
                icon="🏷",
                description="Assign or remove metadata tags (e.g. RPG, Soulslike, FPS, Finished)",
            )
        )

        # Manage Collections
        actions.append(
            GameAction(
                id="manage_collections",
                label="Manage Collections",
                handler=lambda g: None,  # handled via CollectionManager in UI
                icon="📁",
                description="Add or remove this game from custom collections",
            )
        )

        # Save Backups
        actions.append(
            GameAction(
                id="manage_saves",
                label="Save Backups",
                handler=lambda g: None,  # handled via SaveManager in UI
                icon="💾",
                description="Create or restore compressed zip save game backups",
            )
        )

        # Screenshots
        actions.append(
            GameAction(
                id="view_screenshots",
                label="Screenshots",
                handler=lambda g: None,  # handled via ScreenshotManager in UI
                icon="🖼",
                description="Browse discovered game screenshots and metadata",
            )
        )

        # Properties (Game Details)
        actions.append(
            GameAction(
                id="show_properties",
                label="Properties",
                handler=lambda g: None,  # handled via GameDetailsProvider in app loop
                icon="📝",
                description="View complete game details and metadata properties",
            )
        )

        # Edit Properties
        actions.append(
            GameAction(
                id="edit_properties",
                label="Edit Properties",
                handler=lambda g: None,  # handled in UI
                icon="✏",
                description="Change game title, executable path, or launcher settings",
            )
        )

        # Refresh Metadata
        actions.append(
            GameAction(
                id="refresh_metadata",
                label="Refresh Metadata",
                handler=lambda g: self._refresh_game_metadata(g),
                icon="🔄",
                description="Re-query and update artwork and metadata cache",
            )
        )

        # Remove From Library (for Filesystem/Wine custom added games)
        source = (game.source or "").lower().strip()
        if source in ("filesystem", "wine"):
            actions.append(
                GameAction(
                    id="remove_from_library",
                    label="Remove From Library",
                    handler=lambda g: _remove_game_from_library(g),
                    icon="🗑",
                    description="Remove this custom game entry from GameDeck library",
                )
            )

        return actions

    def _refresh_game_metadata(self, game: Game) -> None:
        """Refresh metadata and artwork for a single game."""
        try:
            from gamedeck.metadata_manager import MetadataManager

            manager = MetadataManager()
            manager.resolve_artwork(game)
            manager.enrich(game)
        except Exception as err:
            logger.error("Failed to refresh metadata for '%s': %s", game.name, err)


@dataclass(slots=True)
class SteamActionProvider(BaseActionProvider):
    """Dynamic action provider for Steam games."""

    sources: tuple[str, ...] = ("steam",)

    def get_actions(self, game: Game) -> list[GameAction]:
        actions: list[GameAction] = []
        appid = game.appid or game.id.removeprefix("steam_")

        # 1. Play action
        from gamedeck.launchers import launch

        actions.append(
            GameAction(
                id="play",
                label="Play",
                handler=lambda g: launch(g),
                icon="▶",
                description="Launch game through Steam",
                is_primary=True,
            )
        )

        # 2. Open Steam Store Page
        if appid and appid.isdigit():
            actions.append(
                GameAction(
                    id="open_steam_page",
                    label="Open Steam Page",
                    handler=lambda g, aid=appid: _open_url(f"https://store.steampowered.com/app/{aid}"),
                    icon="🌐",
                    description="Open official Steam store page in browser",
                )
            )

        # 3. Browse Steam Files
        if game.executable is not None:
            actions.append(
                GameAction(
                    id="browse_files",
                    label="Browse Files",
                    handler=lambda g: _open_folder(Path(g.executable) if g.executable else None),
                    icon="📁",
                    description="Open game installation folder",
                )
            )

        return actions


@dataclass(slots=True)
class LutrisActionProvider(BaseActionProvider):
    """Dynamic action provider for Lutris games."""

    sources: tuple[str, ...] = ("lutris",)

    def get_actions(self, game: Game) -> list[GameAction]:
        actions: list[GameAction] = []
        slug = game.appid or game.id.removeprefix("lutris_")

        from gamedeck.launchers import launch

        # 1. Play action
        actions.append(
            GameAction(
                id="play",
                label="Play",
                handler=lambda g: launch(g),
                icon="▶",
                description="Launch game through Lutris",
                is_primary=True,
            )
        )

        # 2. Configure game in Lutris
        lutris_bin = shutil.which("lutris")
        if lutris_bin and slug:
            actions.append(
                GameAction(
                    id="configure",
                    label="Configure",
                    handler=lambda g, s=slug: subprocess.Popen([lutris_bin, f"lutris:rungame-config/{s}"]),
                    icon="⚙",
                    description="Open game configuration in Lutris",
                )
            )

        # 3. Browse Prefix
        prefix_dir = self._find_lutris_prefix(slug)
        if prefix_dir is not None and prefix_dir.exists():
            actions.append(
                GameAction(
                    id="browse_prefix",
                    label="Browse Prefix",
                    handler=lambda g, p=prefix_dir: _open_folder(p),
                    icon="🍷",
                    description="Open Wine prefix directory",
                )
            )

        # 4. Browse Files
        if game.executable is not None:
            actions.append(
                GameAction(
                    id="browse_files",
                    label="Browse Files",
                    handler=lambda g: _open_folder(Path(g.executable) if g.executable else None),
                    icon="📁",
                    description="Open game installation folder",
                )
            )

        return actions

    def _find_lutris_prefix(self, slug: str) -> Path | None:
        """Find Wine prefix configured for a Lutris game."""
        home = Path.home()
        candidates = [
            home / "Games" / slug,
            home / ".local" / "share" / "wineprefixes" / slug,
            home / ".wine",
        ]
        for c in candidates:
            if c.is_dir() and (c / "drive_c").is_dir():
                return c
        return None


@dataclass(slots=True)
class HeroicActionProvider(BaseActionProvider):
    """Dynamic action provider for Heroic Games Launcher games."""

    sources: tuple[str, ...] = ("heroic",)

    def get_actions(self, game: Game) -> list[GameAction]:
        actions: list[GameAction] = []
        from gamedeck.launchers import launch

        # 1. Play action
        actions.append(
            GameAction(
                id="play",
                label="Play",
                handler=lambda g: launch(g),
                icon="▶",
                description="Launch game through Heroic",
                is_primary=True,
            )
        )

        # 2. Browse Files
        if game.executable is not None:
            actions.append(
                GameAction(
                    id="browse_files",
                    label="Browse Files",
                    handler=lambda g: _open_folder(Path(g.executable) if g.executable else None),
                    icon="📁",
                    description="Open game installation folder",
                )
            )

        # 3. Open Heroic client
        heroic_bin = shutil.which("heroic")
        if heroic_bin:
            actions.append(
                GameAction(
                    id="open_heroic",
                    label="Open in Heroic",
                    handler=lambda g: subprocess.Popen([heroic_bin]),
                    icon="🦸",
                    description="Open Heroic Games Launcher GUI",
                )
            )

        return actions


@dataclass(slots=True)
class NativeActionProvider(BaseActionProvider):
    """Dynamic action provider for native Linux desktop games."""

    sources: tuple[str, ...] = ("native",)

    def get_actions(self, game: Game) -> list[GameAction]:
        actions: list[GameAction] = []
        from gamedeck.launchers import launch

        # 1. Launch action
        actions.append(
            GameAction(
                id="launch",
                label="Play",
                handler=lambda g: launch(g),
                icon="▶",
                description="Execute native application",
                is_primary=True,
            )
        )

        # 2. Open Desktop File
        desktop_file = self._find_desktop_file(game)
        if desktop_file is not None and desktop_file.is_file():
            actions.append(
                GameAction(
                    id="open_desktop_file",
                    label="Open Desktop File",
                    handler=lambda g, df=desktop_file: _open_text_file(df),
                    icon="📄",
                    description="View desktop entry configuration file",
                )
            )

        # 3. Open binary folder — uses same id as universal provider so registry deduplicates it

        return actions

    def _find_desktop_file(self, game: Game) -> Path | None:
        """Find the corresponding .desktop file for a native Linux game."""
        stem = game.appid or game.id.removeprefix("native_")
        if not stem:
            return None

        home = Path.home()
        xdg_data = Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share"))
        candidates = [
            Path("/usr/share/applications") / f"{stem}.desktop",
            home / ".local" / "share" / "applications" / f"{stem}.desktop",
            xdg_data / "applications" / f"{stem}.desktop",
        ]
        for c in candidates:
            if c.is_file():
                return c
        return None


@dataclass(slots=True)
class FilesystemActionProvider(BaseActionProvider):
    """Dynamic action provider for standalone filesystem/Wine games."""

    sources: tuple[str, ...] = ("filesystem", "wine")

    def get_actions(self, game: Game) -> list[GameAction]:
        actions: list[GameAction] = []
        from gamedeck.launchers import launch

        # 1. Play action
        actions.append(
            GameAction(
                id="play",
                label="Play",
                handler=lambda g: launch(g),
                icon="▶",
                description="Run standalone executable or Wine binary",
                is_primary=True,
            )
        )

        # 2. Open Folder — handled universally by UniversalActionProvider (deduped by registry)

        return actions


# -----------------------------------------------------------------------------
# Action Registry & Extensible Discovery
# -----------------------------------------------------------------------------


@dataclass(slots=True)
class ActionRegistry:
    """Registry coordinating dynamic action providers."""

    providers: list[BaseActionProvider] = field(default_factory=list)

    @classmethod
    def default(cls) -> ActionRegistry:
        """Construct registry populated with all built-in and discovered providers."""
        reg = cls()
        reg.register_builtins()
        reg.discover_custom_providers()
        return reg

    def register_builtins(self) -> None:
        """Register default core action providers."""
        self.providers.extend(
            [
                UniversalActionProvider(),
                SteamActionProvider(),
                LutrisActionProvider(),
                HeroicActionProvider(),
                NativeActionProvider(),
                FilesystemActionProvider(),
            ]
        )

    def register(self, provider: BaseActionProvider) -> None:
        """Register a custom action provider."""
        self.providers.append(provider)

    def discover_custom_providers(self) -> None:
        """Auto-discover custom action providers located within gamedeck.actions package."""
        try:
            import gamedeck.actions as actions_pkg

            package_dir = Path(actions_pkg.__file__).parent
            for _, mod_name, _ in pkgutil.iter_modules([str(package_dir)]):
                if mod_name in ("__init__",):
                    continue
                try:
                    module = importlib.import_module(f"gamedeck.actions.{mod_name}")
                    for attr_name in dir(module):
                        obj = getattr(module, attr_name)
                        if (
                            isinstance(obj, type)
                            and issubclass(obj, BaseActionProvider)
                            and obj is not BaseActionProvider
                        ):
                            # Instantiate and register if not already present
                            if not any(isinstance(p, obj) for p in self.providers):
                                self.providers.append(obj())
                except Exception as err:
                    logger.debug("Failed to load actions module '%s': %s", mod_name, err)
        except Exception as err:
            logger.debug("Action discovery skipped: %s", err)

    def get_actions(self, game: Game) -> list[GameAction]:
        """Query all applicable actions for a game without hardcoding action lists."""
        all_actions: list[GameAction] = []
        seen_ids: set[str] = set()

        for provider in self.providers:
            if provider.is_applicable(game):
                try:
                    for action in provider.get_actions(game):
                        if action.id not in seen_ids:
                            seen_ids.add(action.id)
                            all_actions.append(action)
                except Exception as err:
                    logger.warning("Error querying action provider %s: %s", provider, err)

        # Fallback default play action if no providers matched
        if not all_actions:
            from gamedeck.launchers import launch

            all_actions.append(
                GameAction(
                    id="play",
                    label="Play",
                    handler=lambda g: launch(g),
                    icon="▶",
                    description="Launch game",
                    is_primary=True,
                )
            )

        return self._order_actions_for_menu(all_actions)

    def _order_actions_for_menu(self, actions: list[GameAction]) -> list[GameAction]:
        """Return actions in the curated context-menu display order."""
        menu_order: tuple[str, ...] = (
            "play",
            "launch",
            "toggle_favorite",
            "open_folder",
            "configure",
            "browse_prefix",
            "select_profile",
            "edit_tags",
            "manage_collections",
            "show_properties",
            "edit_properties",
            "refresh_metadata",
            "remove_from_library",
        )
        by_id = {a.id: a for a in actions}
        ordered: list[GameAction] = []
        seen: set[str] = set()
        for action_id in menu_order:
            action = by_id.get(action_id)
            if action is not None and action_id not in seen:
                ordered.append(action)
                seen.add(action_id)
        for action in actions:
            if action.id not in seen:
                ordered.append(action)
                seen.add(action.id)
        return ordered


_DEFAULT_REGISTRY = ActionRegistry.default()


def get_actions_for_game(game: Game) -> list[GameAction]:
    """Retrieve all available dynamic actions for a game.

    Args:
        game: Game model instance.

    Returns:
        List of GameAction instances.
    """
    return _DEFAULT_REGISTRY.get_actions(game)


def execute_action(action_or_id: GameAction | str, game: Game) -> Any:
    """Execute a specific action for a game.

    Args:
        action_or_id: GameAction instance or action identifier string.
        game: Target Game model.

    Returns:
        Result from the executed action handler.
    """
    if isinstance(action_or_id, GameAction):
        return action_or_id.execute(game)

    actions = get_actions_for_game(game)
    for act in actions:
        if act.id == action_or_id:
            return act.execute(game)

    raise ValueError(f"Action '{action_or_id}' is not valid or available for game '{game.name}'.")
