"""SteamGridDB API client and background asset downloader for GameDeck.

Fetches cover, icon, logo, and hero art from SteamGridDB, caches them locally,
respects rate limits (HTTP 429 and configurable request delays), operates in the
background without blocking the UI, and falls back to application icons.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gamedeck.artwork import ArtworkCache
from gamedeck.models import Game

__all__ = [
    "SteamGridDBClient",
]

logger = logging.getLogger(__name__)

DEFAULT_API_URL = "https://www.steamgriddb.com/api/v2"


@dataclass(slots=True)
class SteamGridDBClient:
    """Client for querying SteamGridDB and queueing non-blocking background artwork fetches.

    Respects API limits:
    - Minimum interval between API requests (default 0.25s)
    - Exponential backoff on HTTP 429 Too Many Requests
    - Non-blocking background worker execution
    - Fallback to local application icons when no artwork is returned

    Attributes:
        api_key: SteamGridDB authentication API token (or from SGDB_API_KEY env).
        artwork_cache: Local ArtworkCache instance.
        base_url: SteamGridDB REST API base URL.
        min_request_interval: Minimum time in seconds between API requests (default 0.25s).
    """

    api_key: str | None = None
    artwork_cache: ArtworkCache = field(default_factory=ArtworkCache)
    base_url: str = DEFAULT_API_URL
    min_request_interval: float = 0.25
    offline_mode: bool = False
    _last_request_time: float = field(default=0.0, init=False, repr=False)

    def __post_init__(self) -> None:
        """Resolve API key from environment if not provided."""
        if not self.api_key:
            self.api_key = os.environ.get("STEAMGRIDDB_API_KEY") or os.environ.get("SGDB_API_KEY")

    def is_available(self) -> bool:
        """Return True if an API key is configured and offline mode is not enabled."""
        return bool(self.api_key) and not self.offline_mode

    def fetch_game_artwork_background(
        self,
        game: Game,
        on_complete: Any = None,
        force: bool = False,
    ) -> None:
        """Submit background download tasks for cover, icon, logo, and hero art for a game.

        Operates asynchronously through ArtworkCache thread pool without delaying UI startup.
        Never re-downloads if all assets already exist locally or offline mode is active, unless force=True.
        """
        if not self.is_available():
            logger.debug("SteamGridDB API unavailable or offline mode active; skipping remote fetch for '%s'", game.name)
            return

        # Check if all primary assets already exist on disk
        has_hero = self.artwork_cache.has_artwork(game.id, "heroes")
        has_cover = self.artwork_cache.has_artwork(game.id, "covers")
        has_icon = self.artwork_cache.has_artwork(game.id, "icons")
        has_logo = self.artwork_cache.has_artwork(game.id, "logos")

        if not force and has_hero and has_cover and has_icon and has_logo:
            return

        def _task() -> None:
            try:
                self._fetch_and_store_all(game, on_complete=on_complete, force=force)
            except Exception as err:
                logger.debug("SteamGridDB artwork download task failed for '%s': %s", game.name, err)

        self.artwork_cache._executor.submit(_task)

    def _fetch_and_store_all(self, game: Game, on_complete: Any = None, force: bool = False) -> None:
        """Search game on SteamGridDB and download missing covers, icons, logos, and heroes."""
        if not self.is_available():
            return

        game_sgdb_id = self.search_game_id(game)
        if not game_sgdb_id:
            logger.debug("SteamGridDB game ID not found for '%s'", game.name)
            return

        # Fetch Grids (Covers)
        if force or not self.artwork_cache.has_artwork(game.id, "covers"):
            cover_url = self._get_best_asset_url(game_sgdb_id, "grids")
            if cover_url:
                self.artwork_cache.fetch_async(game.id, "covers", cover_url, on_complete=on_complete, force=force)

        # Fetch Icons
        if force or not self.artwork_cache.has_artwork(game.id, "icons"):
            icon_url = self._get_best_asset_url(game_sgdb_id, "icons")
            if icon_url:
                self.artwork_cache.fetch_async(game.id, "icons", icon_url, on_complete=on_complete, force=force)

        # Fetch Logos
        if force or not self.artwork_cache.has_artwork(game.id, "logos"):
            logo_url = self._get_best_asset_url(game_sgdb_id, "logos")
            if logo_url:
                self.artwork_cache.fetch_async(game.id, "logos", logo_url, on_complete=on_complete, force=force)

        # Fetch Heroes
        if force or not self.artwork_cache.has_artwork(game.id, "heroes"):
            hero_url = self._get_best_asset_url(game_sgdb_id, "heroes")
            if hero_url:
                self.artwork_cache.fetch_async(game.id, "heroes", hero_url, on_complete=on_complete, force=force)

    def search_game_id(self, game: Game) -> int | None:
        """Search SteamGridDB for a game by Steam appid or normalized game title."""
        # 1. Try by Steam AppID if source is steam
        if game.source == "steam" and game.appid and game.appid.isdigit():
            endpoint = f"{self.base_url}/games/steam/{game.appid}"
            data = self._api_request(endpoint)
            if data and data.get("success") and "data" in data:
                return int(data["data"]["id"])

        # 2. Search by title
        query = urllib.parse.quote(game.name)
        endpoint = f"{self.base_url}/search/autocomplete/{query}"
        data = self._api_request(endpoint)
        if data and data.get("success") and "data" in data and len(data["data"]) > 0:
            return int(data["data"][0]["id"])

        return None

    def _get_best_asset_url(self, sgdb_id: int, asset_type: str) -> str | None:
        """Retrieve highest rated artwork URL for a given game ID and asset type."""
        endpoint = f"{self.base_url}/{asset_type}/game/{sgdb_id}"
        data = self._api_request(endpoint)
        if data and data.get("success") and "data" in data and len(data["data"]) > 0:
            # First item is highest upvoted / default
            return str(data["data"][0].get("url", ""))
        return None

    def _api_request(self, url: str) -> dict[str, Any] | None:
        """Execute a rate-limited HTTP GET request to SteamGridDB API with retry on 429."""
        if not self.api_key:
            return None

        # Rate limiting: ensure min_request_interval between requests
        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < self.min_request_interval:
            time.sleep(self.min_request_interval - elapsed)
        self._last_request_time = time.time()

        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "User-Agent": "GameDeck/0.1.0 (Linux; SteamDeck)",
            },
        )

        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=5.0) as resp:
                    if resp.status == 200:
                        return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as err:
                if err.code == 429:
                    # Rate limit encountered: exponential backoff
                    backoff = (2 ** attempt) * 0.5
                    logger.warning("SteamGridDB rate limit hit (HTTP 429); backing off for %.1fs", backoff)
                    time.sleep(backoff)
                    continue
                elif err.code == 404:
                    return None
                else:
                    logger.debug("SteamGridDB HTTP error %d for %s: %s", err.code, url, err)
                    return None
            except Exception as err:
                logger.debug("SteamGridDB request exception for %s: %s", url, err)
                return None

        return None
