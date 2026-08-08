"""Heroic Games Launcher provider for GameDeck."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gamedeck.models import Game
from gamedeck.providers import BaseProvider

__all__ = ["HeroicProvider", "get_games"]

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class HeroicProvider(BaseProvider):
    """Provider for discovering games managed by Heroic Games Launcher.

    Supports Epic Games (Legendary), GOG (gogdl), Amazon Prime (Nile), and
    sideloaded games across native Linux, Flatpak, and Snap installations.

    Class attributes:
        name: Provider identifier — ``"heroic"``.
        priority: Deduplication precedence — ``40``.

    Attributes:
        heroic_roots: Base directories containing Heroic configuration files.
    """

    name: str = field(default="heroic", init=False, repr=False, compare=False)
    priority: int = field(default=40, init=False, repr=False, compare=False)

    heroic_roots: list[Path] = field(default_factory=list)

    def enabled(self) -> bool:
        """Return ``True`` if at least one Heroic configuration directory exists.

        When no roots were provided at construction, auto-discovery runs first.
        Explicitly-provided roots are used as-is.
        """
        if not self.heroic_roots:
            self.__post_init__()
        return any(r.is_dir() for r in self.heroic_roots)

    def __post_init__(self) -> None:
        """Initialize default Heroic configuration roots if none were provided."""
        if not self.heroic_roots:
            home = Path.home()
            xdg_config = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))

            candidates = [
                xdg_config / "heroic",
                home / ".config" / "heroic",
                home / ".var" / "app" / "com.heroicgameslauncher.hgl" / "config" / "heroic",
                home / "snap" / "heroic-games-launcher" / "current" / ".config" / "heroic",
            ]

            resolved_roots: list[Path] = []
            seen: set[Path] = set()

            for candidate in candidates:
                if candidate.is_dir():
                    try:
                        resolved = candidate.resolve()
                    except OSError:
                        resolved = candidate
                    if resolved not in seen:
                        seen.add(resolved)
                        resolved_roots.append(resolved)

            self.heroic_roots = resolved_roots

    def scan(self) -> list[Game]:
        """Scan all Heroic installation roots and return all discovered games.

        Returns:
            A list of Game model instances for all installed Heroic games.
        """
        games: list[Game] = []
        seen_ids: set[str] = set()

        for root in self.heroic_roots:
            if not root.is_dir():
                continue

            # 1. Epic Games / Legendary store
            epic_games = self._parse_legendary(root)
            for g in epic_games:
                if g.id not in seen_ids:
                    seen_ids.add(g.id)
                    games.append(g)

            # 2. GOG store (gogdl)
            gog_games = self._parse_gog(root)
            for g in gog_games:
                if g.id not in seen_ids:
                    seen_ids.add(g.id)
                    games.append(g)

            # 3. Amazon Prime Gaming (Nile)
            nile_games = self._parse_nile(root)
            for g in nile_games:
                if g.id not in seen_ids:
                    seen_ids.add(g.id)
                    games.append(g)

            # 4. Sideloaded / Custom games
            sideload_games = self._parse_sideload(root)
            for g in sideload_games:
                if g.id not in seen_ids:
                    seen_ids.add(g.id)
                    games.append(g)

        logger.debug("Heroic provider discovered %d games across %d roots", len(games), len(self.heroic_roots))
        return games

    def _parse_legendary(self, root: Path) -> list[Game]:
        """Parse Epic Games Store installed metadata from Legendary."""
        candidates = [
            root / "legendaryConfig" / "legendary" / "installed.json",
            root / "legendary" / "installed.json",
            root / "store_cache" / "legendary_library.json",
        ]
        return self._read_store_json(root, candidates, runner_prefix="legendary")

    def _parse_gog(self, root: Path) -> list[Game]:
        """Parse GOG store installed metadata."""
        candidates = [
            root / "gog_store" / "installed.json",
            root / "gog_store" / "library.json",
            root / "store_cache" / "gog_library.json",
        ]
        return self._read_store_json(root, candidates, runner_prefix="gog")

    def _parse_nile(self, root: Path) -> list[Game]:
        """Parse Amazon Prime Gaming store installed metadata from Nile."""
        candidates = [
            root / "nile_store" / "installed.json",
            root / "nile_store" / "library.json",
            root / "store_cache" / "nile_library.json",
        ]
        return self._read_store_json(root, candidates, runner_prefix="nile")

    def _parse_sideload(self, root: Path) -> list[Game]:
        """Parse sideloaded / custom games installed in Heroic."""
        candidates = [
            root / "sideload_apps" / "library.json",
            root / "sideload_apps" / "installed.json",
            root / "games.json",
        ]
        return self._read_store_json(root, candidates, runner_prefix="sideload")

    def _read_store_json(
        self,
        root: Path,
        candidates: list[Path],
        runner_prefix: str,
    ) -> list[Game]:
        """Read and convert store configuration files into Game model instances."""
        games: list[Game] = []

        for path in candidates:
            if not path.is_file():
                continue

            try:
                with path.open("r", encoding="utf-8", errors="replace") as f:
                    data = json.load(f)
            except (OSError, json.JSONDecodeError) as err:
                logger.debug("Skipping unreadable Heroic json '%s': %s", path, err)
                continue

            items: list[dict[str, Any]] = []
            if isinstance(data, list):
                items = [item for item in data if isinstance(item, dict)]
            elif isinstance(data, dict):
                # Heroic structures installed.json as either { "appName": {...} } or { "installed": [...] }
                if "installed" in data and isinstance(data["installed"], list):
                    items = [item for item in data["installed"] if isinstance(item, dict)]
                elif "apps" in data and isinstance(data["apps"], list):
                    items = [item for item in data["apps"] if isinstance(item, dict)]
                else:
                    for key, val in data.items():
                        if isinstance(val, dict):
                            val_copy = dict(val)
                            if "app_name" not in val_copy and "appName" not in val_copy:
                                val_copy["app_name"] = key
                            items.append(val_copy)

            for item in items:
                game = self._build_game_model(root, item, runner_prefix)
                if game is not None:
                    games.append(game)

        return games

    def _build_game_model(
        self,
        root: Path,
        item: dict[str, Any],
        runner_prefix: str,
    ) -> Game | None:
        """Construct a Game dataclass instance from a Heroic entry."""
        # Resolve App Name / Slug identifier
        app_name = (
            item.get("app_name")
            or item.get("appName")
            or item.get("id")
            or item.get("appId")
        )
        if not app_name or not str(app_name).strip():
            return None

        app_name_str = str(app_name).strip()

        # Resolve Game display title
        title = (
            item.get("title")
            or item.get("name")
            or item.get("game_title")
        )
        if not title or not str(title).strip():
            title = app_name_str.replace("_", " ").replace("-", " ").title()

        title_str = str(title).strip()

        # Resolve installation path and executable
        install_path_raw = item.get("install_path") or item.get("install_dir") or item.get("folder_name")
        executable_raw = item.get("executable") or item.get("exe") or item.get("binary")

        executable_path: Path | None = None
        if install_path_raw:
            inst_p = Path(str(install_path_raw).strip())
            if executable_raw:
                exe_p = inst_p / str(executable_raw).strip()
                executable_path = exe_p if exe_p.exists() else inst_p
            elif inst_p.exists():
                executable_path = inst_p
        elif executable_raw:
            exe_p = Path(str(executable_raw).strip())
            if exe_p.exists():
                executable_path = exe_p

        # Determine installation status
        is_installed = item.get("is_installed", True)
        if isinstance(is_installed, bool) and not is_installed:
            return None

        # Build unique identifier
        game_id = f"heroic_{app_name_str}"

        # Favorite status
        favorite = bool(item.get("favorite", False))

        # Discover native Heroic icon
        heroic_icon = self._resolve_heroic_icon(root, app_name_str)

        return Game(
            id=game_id,
            name=title_str,
            source="heroic",
            launcher="heroic",
            executable=executable_path,
            icon=heroic_icon,
            cover=None,
            installed=True,
            favorite=favorite,
            appid=app_name_str,
        )


    def _resolve_heroic_icon(self, root: Path, app_name: str) -> Path | None:
        """Resolve native application icon for a Heroic game from icons folder or image cache."""
        if not app_name:
            return None

        candidates = [
            root / "icons" / f"{app_name}.png",
            root / "icons" / f"{app_name}.jpg",
            root / "store_cache" / "images" / f"{app_name}.png",
            root / "store_cache" / "images" / f"{app_name}.jpg",
        ]
        for c in candidates:
            if c.is_file() and c.stat().st_size > 0:
                return c

        return None


def get_games(heroic_roots: list[Path] | None = None) -> list[Game]:
    """Retrieve all discovered Heroic games across all configured stores.

    Args:
        heroic_roots: Optional list of base Heroic installation roots.

    Returns:
        A list of Game model instances.
    """
    provider = HeroicProvider(heroic_roots=heroic_roots or [])
    return provider.get_games()
