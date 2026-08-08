"""Configuration management and settings model for GameDeck."""

from __future__ import annotations

import logging
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "Settings",
    "ProvidersConfig",
    "FilesystemConfig",
    "UIConfig",
    "LaunchConfig",
    "load_settings",
    "get_default_config_path",
]

logger = logging.getLogger(__name__)


def get_default_config_path() -> Path:
    """Return standard path to the GameDeck configuration file (~/.config/gamedeck/config.toml)."""
    xdg_config = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return xdg_config / "gamedeck" / "config.toml"


@dataclass(slots=True)
class ProvidersConfig:
    """Configuration toggles for individual game providers.

    Attributes:
        steam: Whether the Steam library provider is enabled.
        lutris: Whether the Lutris library provider is enabled.
        heroic: Whether the Heroic Games Launcher provider is enabled.
        filesystem: Whether the local filesystem provider is enabled.
        native: Whether the native Linux binaries provider is enabled.
    """

    steam: bool = True
    lutris: bool = True
    heroic: bool = True
    filesystem: bool = True
    native: bool = True

    def enabled_list(self) -> list[str]:
        """Return a list of enabled provider identifiers."""
        toggles = [
            ("steam", self.steam),
            ("heroic", self.heroic),
            ("lutris", self.lutris),
            ("native", self.native),
            ("filesystem", self.filesystem),
        ]
        return [name for name, enabled in toggles if enabled]


@dataclass(slots=True)
class FilesystemConfig:
    """Configuration options for filesystem game discovery.

    Attributes:
        search_paths: List of directory paths to scan for installed game executables.
    """

    search_paths: list[Path] = field(
        default_factory=lambda: [
            Path("/mnt/windows/Games"),
            Path("~/Games"),
        ]
    )

    def resolved_paths(self) -> list[Path]:
        """Return search paths with user home directory symbols (~/...) expanded."""
        expanded: list[Path] = []
        for p in self.search_paths:
            path_obj = Path(p).expanduser()
            expanded.append(path_obj)
        return expanded


@dataclass(slots=True)
class UIConfig:
    """Configuration options for the graphical user interface.

    Attributes:
        rofi_theme: Optional path or name of the Rofi .rasi theme to use.
        recent_games_limit: Maximum number of recently played games to prioritize.
        show_recently_played: Whether recently played games are prioritized above the alphabetical list.
        secondary_action_key: Rofi keybinding (custom-1) to open the action menu instead of launching.
        steamgriddb_api_key: Optional SteamGridDB API key for automatic artwork downloads.
    """

    rofi_theme: str = ""
    recent_games_limit: int = 5
    show_recently_played: bool = True
    quick_launch: bool = False
    secondary_action_key: str = "Alt+Return"
    steamgriddb_api_key: str = ""


@dataclass(slots=True)
class LaunchConfig:
    """Configuration options for launcher backends and execution methods.

    Attributes:
        default_windows_launcher: Default launcher backend for Windows executables ('lutris' or 'wine').
    """

    default_windows_launcher: str = "lutris"


@dataclass(slots=True)
class Settings:
    """Root GameDeck application configuration settings.

    Attributes:
        providers: Provider enable/disable toggles.
        filesystem: Filesystem discovery settings and search directories.
        ui: User interface and theme settings.
        launch: Execution and launcher backend preferences.
    """

    providers: ProvidersConfig = field(default_factory=ProvidersConfig)
    filesystem: FilesystemConfig = field(default_factory=FilesystemConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    launch: LaunchConfig = field(default_factory=LaunchConfig)

    @classmethod
    def load(cls, config_path: Path | str | None = None) -> Settings:
        """Load settings from a TOML configuration file, falling back to defaults if not found.

        Args:
            config_path: Path to TOML config file, or None to use default location.

        Returns:
            A Settings instance initialized with parsed values and defaults.
        """
        target_path = Path(config_path) if config_path is not None else get_default_config_path()

        if not target_path.is_file():
            logger.debug("Config file '%s' not found, using default settings", target_path)
            return cls()

        try:
            with target_path.open("rb") as f:
                data = tomllib.load(f)
            logger.debug("Successfully loaded config from '%s'", target_path)
            return cls.from_dict(data)
        except (OSError, tomllib.TOMLDecodeError) as err:
            logger.warning("Failed to parse config file '%s': %s (using defaults)", target_path, err)
            return cls()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Settings:
        """Construct a Settings instance from a parsed TOML dictionary.

        Args:
            data: Parsed configuration dictionary.

        Returns:
            A validated Settings instance.
        """
        # Parse providers section
        prov_dict = data.get("providers", {})
        providers = ProvidersConfig(
            steam=bool(prov_dict.get("steam", True)),
            lutris=bool(prov_dict.get("lutris", True)),
            heroic=bool(prov_dict.get("heroic", True)),
            filesystem=bool(prov_dict.get("filesystem", True)),
            native=bool(prov_dict.get("native", True)),
        )

        # Parse filesystem section
        fs_dict = data.get("filesystem", {})
        raw_paths = fs_dict.get("search_paths")
        if isinstance(raw_paths, list):
            search_paths = [Path(str(p)) for p in raw_paths]
        else:
            search_paths = [Path("/mnt/windows/Games"), Path("~/Games")]
        filesystem = FilesystemConfig(search_paths=search_paths)

        # Parse UI section
        ui_dict = data.get("ui", {})
        sgdb_dict = data.get("steamgriddb", {})
        sgdb_key = str(sgdb_dict.get("api_key", ui_dict.get("steamgriddb_api_key", ""))).strip()

        if sgdb_key and not os.environ.get("STEAMGRIDDB_API_KEY"):
            os.environ["STEAMGRIDDB_API_KEY"] = sgdb_key

        ui = UIConfig(
            rofi_theme=str(ui_dict.get("rofi_theme", "")),
            recent_games_limit=int(ui_dict.get("recent_games_limit", 5)),
            show_recently_played=bool(ui_dict.get("show_recently_played", True)),
            quick_launch=bool(ui_dict.get("quick_launch", False)),
            secondary_action_key=str(ui_dict.get("secondary_action_key", "Alt+Return")),
            steamgriddb_api_key=sgdb_key,
        )

        # Parse launch section
        launch_dict = data.get("launch", {})
        launch = LaunchConfig(
            default_windows_launcher=str(launch_dict.get("default_windows_launcher", "lutris")),
        )

        return cls(
            providers=providers,
            filesystem=filesystem,
            ui=ui,
            launch=launch,
        )


def load_settings(config_path: Path | str | None = None) -> Settings:
    """Convenience function to load application settings.

    Args:
        config_path: Optional path to TOML configuration file.

    Returns:
        Loaded Settings instance.
    """
    return Settings.load(config_path=config_path)
