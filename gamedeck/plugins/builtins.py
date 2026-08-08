"""Built-in plugin implementations for GameDeck's core services.

Registers the SteamGridDB client as a ``BaseArtworkSourcePlugin`` so that the
artwork resolution pipeline is itself pluggable. Third-party artwork sources
(e.g. IGDB, RAWG, VNDB) can register alongside this built-in without any
modification to core GameDeck code.
"""

from __future__ import annotations

from typing import Any

from gamedeck.models import Game
from gamedeck.plugins import BaseArtworkSourcePlugin

__all__ = ["SteamGridDBArtworkPlugin"]


class SteamGridDBArtworkPlugin(BaseArtworkSourcePlugin):
    """Built-in artwork source backed by SteamGridDB.

    Wraps :class:`~gamedeck.steamgriddb.SteamGridDBClient` in the
    :class:`~gamedeck.plugins.BaseArtworkSourcePlugin` contract so it can
    co-exist with (and be replaced by) community artwork source plugins.

    Attributes:
        name: Plugin identifier used for registration lookup.
        display_name: Human-readable name shown in plugin lists.
        priority: Lower numbers are tried first; SteamGridDB is priority 10 (high).
    """

    name: str = "steamgriddb"
    display_name: str = "SteamGridDB"
    priority: int = 10

    def __init__(self, api_key: str = "") -> None:
        """Initialize with optional API key.

        Args:
            api_key: SteamGridDB API key. Falls back to STEAMGRIDDB_API_KEY env var.
        """
        self._api_key = api_key

    def is_available(self) -> bool:
        """Return True if a SteamGridDB API key is configured."""
        from gamedeck.steamgriddb import SteamGridDBClient
        client = SteamGridDBClient(api_key=self._api_key)
        return client.is_available()

    def fetch_artwork_urls(self, game: Game, art_type: str) -> list[str]:
        """Fetch SteamGridDB artwork URLs for a game.

        Args:
            game: Target game model.
            art_type: One of 'icon', 'logo', 'hero', 'cover'.

        Returns:
            List of image URLs ordered by SteamGridDB relevance score.
        """
        from gamedeck.steamgriddb import SteamGridDBClient
        client = SteamGridDBClient(api_key=self._api_key)
        if not client.is_available():
            return []
        try:
            endpoint_map = {
                "icon": "icons",
                "logo": "logos",
                "hero": "heroes",
                "cover": "grids",
            }
            endpoint = endpoint_map.get(art_type.lower(), "grids")
            appid = game.appid or ""
            source = (game.source or "").lower()
            if source == "steam" and appid.isdigit():
                game_id_raw = appid
            else:
                search_result = client._search_game(game.name)
                if not search_result:
                    return []
                game_id_raw = str(search_result)
            urls = client._fetch_image_urls(game_id_raw, endpoint)
            return urls or []
        except Exception:
            return []


def register_builtins(registry: Any) -> None:
    """Register all built-in plugins with the given PluginRegistry.

    Args:
        registry: :class:`~gamedeck.plugins.PluginRegistry` instance.
    """
    try:
        plugin = SteamGridDBArtworkPlugin()
        registry.register_artwork_source(plugin)
    except Exception:
        pass  # Builtins should never crash startup
