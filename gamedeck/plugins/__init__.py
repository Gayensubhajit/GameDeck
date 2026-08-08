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


@dataclass(slots=True)
class PluginRegistry:
    """Central registry managing provider and launcher plugins."""

    provider_plugins: dict[str, BaseProviderPlugin] = field(default_factory=dict)
    launcher_plugins: dict[str, BaseLauncherPlugin] = field(default_factory=dict)

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


def get_plugin_registry() -> PluginRegistry:
    """Convenience function to get shared PluginRegistry instance."""
    return PluginRegistry.get_instance()
