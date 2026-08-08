"""Plugin system architecture for GameDeck enabling auto-registered providers and launchers."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Type

from gamedeck.models import Game

__all__ = [
    "BaseProviderPlugin",
    "BaseLauncherPlugin",
    "BaseMetadataSourcePlugin",
    "BaseArtworkSourcePlugin",
    "BaseViewPlugin",
    "BaseStatisticsPlugin",
    "PluginRegistry",
    "get_plugin_registry",
]

logger = logging.getLogger(__name__)


class BaseProviderPlugin(ABC):
    """Abstract base class for all game library provider plugins."""

    name: str
    display_name: str
    enabled_by_default: bool = True

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if provider environment or data paths exist."""
        pass

    @abstractmethod
    def scan(self) -> list[Game]:
        """Discover and return all installed Game models for this provider."""
        pass

    def compute_fingerprint(self) -> str:
        """Return modification fingerprint hash for incremental change detection."""
        return self.name


class BaseLauncherPlugin(ABC):
    """Abstract base class for custom execution launcher plugins."""

    name: str
    display_name: str

    @abstractmethod
    def can_launch(self, game: Game) -> bool:
        """Return True if this launcher can execute the target Game."""
        pass

    @abstractmethod
    def launch(self, game: Game, profile: Any | None = None) -> Any:
        """Execute the target Game."""
        pass


class BaseMetadataSourcePlugin(ABC):
    """Abstract base class for metadata source plugins.

    Plugins implementing this class can supply additional metadata fields
    (descriptions, genres, release dates, screenshots) for games without
    modifying core GameDeck code.
    """

    name: str
    display_name: str
    priority: int = 50  # Lower numbers = higher priority

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if this metadata source is configured and accessible."""
        pass

    @abstractmethod
    def fetch_metadata(self, game: Game) -> dict[str, Any]:
        """Fetch and return a metadata dict for the given game.

        Returns a dict with any subset of keys: 'description', 'genres',
        'release_date', 'developer', 'publisher', 'rating', 'screenshots'.
        """
        pass


class BaseArtworkSourcePlugin(ABC):
    """Abstract base class for artwork source plugins.

    The built-in SteamGridDB client is effectively a built-in artwork source.
    Third-party artwork sources (IGDB, RAWG, etc.) can register here without
    modifying core artwork resolution logic.
    """

    name: str
    display_name: str
    priority: int = 50

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if this artwork source is configured and accessible."""
        pass

    @abstractmethod
    def fetch_artwork_urls(self, game: Game, art_type: str) -> list[str]:
        """Fetch a prioritized list of artwork URLs for a given game and type.

        Args:
            game: Target game.
            art_type: One of 'icon', 'logo', 'hero', 'cover'.

        Returns:
            Ordered list of artwork URLs (best match first).
        """
        pass


class BaseViewPlugin(ABC):
    """Abstract base class for custom library view plugins.

    Plugins register new LibraryView implementations that become available
    via --view CLI flag and ViewManager without modifying core code.
    """

    @abstractmethod
    def get_view(self) -> Any:  # Returns LibraryView
        """Return the LibraryView instance provided by this plugin."""
        pass


class BaseStatisticsPlugin(ABC):
    """Abstract base class for library statistics provider plugins."""

    name: str
    display_name: str

    @abstractmethod
    def collect(self, games: list[Game]) -> dict[str, Any]:
        """Collect and return statistics as a key-value dict."""
        pass


@dataclass(slots=True)
class PluginRegistry:
    """Central registry managing provider, launcher, and extension plugins."""

    provider_plugins: dict[str, BaseProviderPlugin] = field(default_factory=dict)
    launcher_plugins: dict[str, BaseLauncherPlugin] = field(default_factory=dict)
    metadata_source_plugins: dict[str, BaseMetadataSourcePlugin] = field(default_factory=dict)
    artwork_source_plugins: dict[str, BaseArtworkSourcePlugin] = field(default_factory=dict)
    view_plugins: dict[str, BaseViewPlugin] = field(default_factory=dict)
    statistics_plugins: dict[str, BaseStatisticsPlugin] = field(default_factory=dict)

    _instance: PluginRegistry | None = None

    @classmethod
    def get_instance(cls) -> PluginRegistry:
        """Return global singleton PluginRegistry instance."""
        if cls._instance is None:
            cls._instance = PluginRegistry()
        return cls._instance

    def register_provider(self, plugin: BaseProviderPlugin) -> None:
        """Register a provider plugin instance."""
        self.provider_plugins[plugin.name.lower().strip()] = plugin
        logger.debug("Registered provider plugin '%s' (%s)", plugin.name, plugin.display_name)

    def register_launcher(self, plugin: BaseLauncherPlugin) -> None:
        """Register a launcher plugin instance."""
        self.launcher_plugins[plugin.name.lower().strip()] = plugin
        logger.debug("Registered launcher plugin '%s' (%s)", plugin.name, plugin.display_name)

    def get_provider(self, name: str) -> BaseProviderPlugin | None:
        """Retrieve registered provider plugin by name."""
        return self.provider_plugins.get(name.lower().strip())

    def get_launcher(self, name: str) -> BaseLauncherPlugin | None:
        """Retrieve registered launcher plugin by name."""
        return self.launcher_plugins.get(name.lower().strip())

    def get_all_providers(self) -> list[BaseProviderPlugin]:
        """Return list of all registered provider plugins."""
        return list(self.provider_plugins.values())

    def register_metadata_source(self, plugin: BaseMetadataSourcePlugin) -> None:
        """Register a metadata source plugin."""
        self.metadata_source_plugins[plugin.name.lower().strip()] = plugin
        logger.debug("Registered metadata source plugin '%s'", plugin.name)

    def get_metadata_source(self, name: str) -> BaseMetadataSourcePlugin | None:
        """Retrieve a metadata source plugin by name."""
        return self.metadata_source_plugins.get(name.lower().strip())

    def get_all_metadata_sources(self) -> list[BaseMetadataSourcePlugin]:
        """Return all metadata source plugins sorted by priority."""
        return sorted(self.metadata_source_plugins.values(), key=lambda p: p.priority)

    def register_artwork_source(self, plugin: BaseArtworkSourcePlugin) -> None:
        """Register an artwork source plugin."""
        self.artwork_source_plugins[plugin.name.lower().strip()] = plugin
        logger.debug("Registered artwork source plugin '%s'", plugin.name)

    def get_all_artwork_sources(self) -> list[BaseArtworkSourcePlugin]:
        """Return all artwork source plugins sorted by priority."""
        return sorted(self.artwork_source_plugins.values(), key=lambda p: p.priority)

    def register_view(self, plugin: BaseViewPlugin) -> None:
        """Register a view plugin. The view is accessible immediately via ViewManager."""
        view = plugin.get_view()
        self.view_plugins[view.name.lower()] = plugin
        logger.debug("Registered view plugin '%s'", view.name)

    def get_all_view_plugins(self) -> list[BaseViewPlugin]:
        """Return all registered view plugins."""
        return list(self.view_plugins.values())

    def register_statistics(self, plugin: BaseStatisticsPlugin) -> None:
        """Register a statistics provider plugin."""
        self.statistics_plugins[plugin.name.lower().strip()] = plugin
        logger.debug("Registered statistics plugin '%s'", plugin.name)

    def get_all_statistics_plugins(self) -> list[BaseStatisticsPlugin]:
        """Return all registered statistics plugins."""
        return list(self.statistics_plugins.values())


def get_plugin_registry() -> PluginRegistry:
    """Convenience function to get shared PluginRegistry instance."""
    return PluginRegistry.get_instance()
