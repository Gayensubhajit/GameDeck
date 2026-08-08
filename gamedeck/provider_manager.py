"""Provider manager for aggregating, deduplicating, and prioritizing game libraries with incremental caching."""

from __future__ import annotations

import importlib
import logging
import pkgutil
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from gamedeck.database import MetadataCache
from gamedeck.models import Game
from gamedeck.providers import BaseProvider

__all__ = ["ProviderManager", "get_all_games", "sort_games_with_recents", "PROVIDER_PRIORITY"]

logger = logging.getLogger(__name__)

# Provider priority hierarchy (higher value = higher precedence)
# Order: Steam > Heroic > Lutris > Native > Filesystem
PROVIDER_PRIORITY: dict[str, int] = {
    "steam": 50,
    "heroic": 40,
    "lutris": 30,
    "native": 20,
    "filesystem": 10,
}


def sort_games_with_recents(games: list[Game], recent_limit: int = 5) -> list[Game]:
    """Sort games prioritizing favorites first, recently played second, and alphabetical library third.

    Args:
        games: List of Game instances to sort.
        recent_limit: Maximum number of recently played games to prioritize.

    Returns:
        Ordered list of Game model instances.
    """
    favorites: list[Game] = []
    non_favorites: list[Game] = []

    for g in games:
        if g.favorite:
            favorites.append(g)
        else:
            non_favorites.append(g)

    # 1. Favorites sorted alphabetically
    fav_sorted = sorted(favorites, key=lambda g: (g.name.lower().strip(), g.id))

    # 2. Recently played games (with recorded last_played timestamp) sorted newest first
    recents = [g for g in non_favorites if g.last_played is not None]
    recents_sorted = sorted(recents, key=lambda g: str(g.last_played), reverse=True)[:recent_limit]
    recent_ids = {g.id for g in recents_sorted}

    # 3. Remaining games sorted alphabetically by title
    library = [g for g in non_favorites if g.id not in recent_ids]
    library_sorted = sorted(library, key=lambda g: (g.name.lower().strip(), g.id))

    return fav_sorted + recents_sorted + library_sorted


def _discover_provider_classes() -> dict[str, type[BaseProvider]]:
    """Walk the ``gamedeck.providers`` package and collect all concrete BaseProvider subclasses.

    Each submodule is imported; any class that is a strict, non-abstract subclass
    of ``BaseProvider`` with a ``name`` attribute is registered.

    Returns:
        A mapping of provider name → provider class.
    """
    import gamedeck.providers as _providers_pkg

    registry: dict[str, type[BaseProvider]] = {}

    pkg_path = _providers_pkg.__path__  # type: ignore[attr-defined]
    pkg_name = _providers_pkg.__name__

    for module_info in pkgutil.iter_modules(pkg_path):
        module_name = f"{pkg_name}.{module_info.name}"
        try:
            module = importlib.import_module(module_name)
        except Exception as err:  # pragma: no cover
            logger.warning("Failed to import provider module '%s': %s", module_name, err)
            continue

        for attr_name in dir(module):
            obj = getattr(module, attr_name)
            if (
                isinstance(obj, type)
                and issubclass(obj, BaseProvider)
                and obj is not BaseProvider
                and not getattr(obj, "__abstractmethods__", None)
                and hasattr(obj, "name")
            ):
                try:
                    instance = obj.__new__(obj)
                    provider_name: str = obj.__dataclass_fields__["name"].default  # type: ignore[attr-defined]
                except Exception:
                    provider_name = getattr(obj, "name", attr_name.lower())

                if provider_name and provider_name not in registry:
                    registry[provider_name] = obj
                    logger.debug("Discovered provider '%s' from %s", provider_name, module_name)

    return registry


@dataclass(slots=True)
class ProviderManager:
    """Manager for orchestrating game discovery across all enabled providers with incremental caching.

    Automatically discovers concrete :class:`~gamedeck.providers.BaseProvider`
    subclasses from the ``gamedeck.providers`` package at construction time.

    On cold start (first run):
        Performs a full scan across all providers and stores games and fingerprints.

    On subsequent runs (incremental):
        Computes provider modification fingerprints. Only rescans modified providers
        and loads unmodified providers directly from the SQLite library cache.

    Attributes:
        enabled_providers: Optional explicit list of provider names to query.
        custom_providers: Mapping of provider names to pre-instantiated provider objects.
        recent_limit: Maximum number of recently played games to prioritize.
        metadata_cache: SQLite database metadata and library cache.
    """

    enabled_providers: list[str] = field(
        default_factory=lambda: ["steam", "heroic", "lutris", "native", "filesystem"]
    )
    custom_providers: dict[str, Callable[[], list[Game]] | BaseProvider] = field(
        default_factory=dict
    )
    recent_limit: int = 5
    metadata_cache: MetadataCache = field(default_factory=MetadataCache)

    def get_games(self, force_full_scan: bool = False) -> list[Game]:
        """Query all enabled providers incrementally or via full scan and return deduplicated games.

        Args:
            force_full_scan: If True, forces full filesystem rescan bypassing the incremental cache.

        Returns:
            A sorted and deduplicated list of Game instances.
        """
        all_games: list[Game] = []

        # 1. Collect games from custom providers first (they shadow built-ins)
        for provider_key, custom in self.custom_providers.items():
            if self.enabled_providers and provider_key.lower() not in [
                p.lower() for p in self.enabled_providers
            ]:
                continue
            games = self._run_custom_provider(provider_key, custom)
            all_games.extend(games)

        # 2. Collect games from auto-discovered built-in providers (incrementally or full scan)
        custom_keys = {k.lower() for k in self.custom_providers}
        registry = _discover_provider_classes()

        for provider_name, provider_cls in registry.items():
            if provider_name in custom_keys:
                continue

            if self.enabled_providers and provider_name not in [
                p.lower().strip() for p in self.enabled_providers
            ]:
                continue

            games = self._get_games_for_provider(provider_name, provider_cls, force_full_scan=force_full_scan)
            all_games.extend(games)

        merged = self.merge_and_deduplicate(all_games)
        logger.debug(
            "ProviderManager merged %d total entries down to %d unique games",
            len(all_games),
            len(merged),
        )
        return merged

    def _get_games_for_provider(
        self,
        provider_name: str,
        provider_cls: type[BaseProvider],
        force_full_scan: bool = False,
    ) -> list[Game]:
        """Fetch games for a single provider, using incremental cache if unmodified."""
        try:
            provider = provider_cls()
        except Exception as err:
            logger.warning("Failed to instantiate provider '%s': %s", provider_name, err)
            return []

        try:
            if not provider.enabled():
                logger.debug("Provider '%s' is disabled — skipping.", provider_name)
                return []
        except Exception as err:
            logger.warning("Provider '%s' enabled() raised an error: %s", provider_name, err)
            return []

        # Compute provider root directories for change detection
        scan_roots = self._get_provider_scan_roots(provider)
        current_fp = self.metadata_cache.compute_provider_fingerprint(provider_name, scan_roots)

        # Incremental check: if unmodified and not forced, load from SQLite
        if not force_full_scan and not self.metadata_cache.is_provider_modified(provider_name, current_fp):
            cached = self.metadata_cache.get_cached_games_for_provider(provider_name)
            if cached:
                logger.debug("Incremental scan: '%s' unmodified — loaded %d games from SQLite cache", provider_name, len(cached))
                return cached

        # Otherwise full scan for this provider
        try:
            games = provider.scan()
            logger.debug("Full scan: provider '%s' returned %d game(s).", provider_name, len(games))
            self.metadata_cache.save_cached_games_for_provider(provider_name, games, fingerprint=current_fp)
            return games
        except Exception as err:
            logger.warning("Provider '%s' failed during scan(): %s", provider_name, err)
            return []

    def _get_provider_scan_roots(self, provider: BaseProvider) -> list[Path]:
        """Extract scan root directories from a provider for fingerprinting."""
        roots: list[Path] = []
        for attr in ("steam_roots", "config_dirs", "heroic_roots", "app_dirs", "search_dirs"):
            val = getattr(provider, attr, None)
            if isinstance(val, list):
                roots.extend([p for p in val if isinstance(p, Path)])
        return roots

    def merge_and_deduplicate(self, games: list[Game]) -> list[Game]:
        """Deduplicate games by unique identifier and name, applying provider precedence and recent sorting.

        When duplicate names or unique IDs exist, the game from the higher priority
        provider (Steam > Heroic > Lutris > Native > Filesystem) is retained.

        Args:
            games: Unfiltered list of Game instances from all providers.

        Returns:
            A deduplicated list of Game instances sorted by Favorites -> Recents -> Alphabetical.
        """
        # Pass 1: Deduplicate by unique game id
        by_id: dict[str, Game] = {}
        for game in games:
            if not game.id:
                continue
            if game.id not in by_id:
                by_id[game.id] = game
            else:
                existing = by_id[game.id]
                if self._get_priority(game.source) > self._get_priority(existing.source):
                    by_id[game.id] = game

        # Pass 2: Deduplicate by normalized title
        by_title: dict[str, Game] = {}
        for game in by_id.values():
            title_key = self.normalize_title(game.name)
            if not title_key:
                title_key = f"__id_{game.id}"

            if title_key not in by_title:
                by_title[title_key] = game
            else:
                existing = by_title[title_key]
                if self._get_priority(game.source) > self._get_priority(existing.source):
                    by_title[title_key] = game

        # Sort: Favorites -> Recently Played -> Alphabetical
        return sort_games_with_recents(list(by_title.values()), recent_limit=self.recent_limit)

    def normalize_title(self, name: str) -> str:
        """Normalize game title for duplicate matching across different providers."""
        lowered = name.lower().strip()
        cleaned = re.sub(r"[^a-z0-9]+", "", lowered)
        return cleaned

    def _get_priority(self, source: str) -> int:
        """Get numerical precedence for a provider source name."""
        key = source.lower().strip()
        registry = _discover_provider_classes()
        cls = registry.get(key)
        if cls is not None:
            try:
                return int(cls.__dataclass_fields__["priority"].default)  # type: ignore[attr-defined]
            except Exception:
                pass
        return PROVIDER_PRIORITY.get(key, 0)

    def _run_builtin_provider(
        self,
        provider_name: str,
        provider_cls: type[BaseProvider],
    ) -> list[Game]:
        """Instantiate a discovered provider, check enabled(), and call scan()."""
        try:
            provider = provider_cls()
        except Exception as err:
            logger.warning("Failed to instantiate provider '%s': %s", provider_name, err)
            return []

        try:
            if not provider.enabled():
                logger.debug("Provider '%s' is disabled — skipping.", provider_name)
                return []
        except Exception as err:
            logger.warning("Provider '%s' enabled() raised an error: %s", provider_name, err)
            return []

        try:
            games = provider.scan()
            logger.debug("Provider '%s' returned %d game(s).", provider_name, len(games))
            return games
        except Exception as err:
            logger.warning("Provider '%s' failed during scan(): %s", provider_name, err)
            return []

    def _run_custom_provider(
        self,
        provider_key: str,
        provider: Callable[[], list[Game]] | BaseProvider,
    ) -> list[Game]:
        """Execute a caller-supplied custom provider instance or callable."""
        try:
            games: list[Game] = []
            if isinstance(provider, BaseProvider):
                if not provider.enabled():
                    logger.debug("Custom provider '%s' is disabled — skipping.", provider_key)
                    return []
                games = provider.scan()
            elif hasattr(provider, "get_games") and callable(provider.get_games):  # type: ignore[union-attr]
                games = provider.get_games()  # type: ignore[union-attr]
            elif callable(provider):
                games = provider()

            scan_roots = self._get_provider_scan_roots(provider) if isinstance(provider, BaseProvider) else []
            fp = self.metadata_cache.compute_provider_fingerprint(provider_key, scan_roots)
            self.metadata_cache.save_cached_games_for_provider(provider_key, games, fingerprint=fp)
            return games
        except Exception as err:
            logger.warning("Custom provider '%s' failed: %s", provider_key, err)
        return []

    def _load_provider_games(self, provider_key: str) -> list[Game]:
        """Execute a single provider and retrieve its games safely."""
        key = provider_key.lower().strip()
        if key in self.custom_providers:
            return self._run_custom_provider(key, self.custom_providers[key])

        registry = _discover_provider_classes()
        cls = registry.get(key)
        if cls is None:
            logger.debug("No provider found for key '%s'.", key)
            return []

        return self._run_builtin_provider(key, cls)


def get_all_games(enabled_providers: list[str] | None = None) -> list[Game]:
    """Retrieve all discovered, metadata-enriched, and deduplicated games across enabled providers."""
    from gamedeck.scanner import scan_games

    return scan_games(enabled_providers=enabled_providers)
