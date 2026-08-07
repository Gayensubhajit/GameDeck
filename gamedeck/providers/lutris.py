"""Lutris game provider for GameDeck."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from gamedeck.models import Game

__all__ = ["LutrisProvider", "get_games"]


@dataclass(slots=True)
class LutrisProvider:
    """Provider for scanning and loading games configured in Lutris.

    Reads Lutris YAML configuration files from user config directories without
    executing the Lutris client or launching any games.

    Attributes:
        config_dirs: Directories to scan for Lutris game YAML files.
        banner_dirs: Directories containing Lutris game banners/cover art.
        coverart_dirs: Directories containing Lutris cover art.
        icon_dirs: Directories containing application and Lutris icons.
    """

    config_dirs: list[Path] = field(default_factory=list)
    banner_dirs: list[Path] = field(default_factory=list)
    coverart_dirs: list[Path] = field(default_factory=list)
    icon_dirs: list[Path] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Initialize default search paths if none were explicitly provided."""
        home = Path.home()
        xdg_config = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
        xdg_data = Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share"))
        xdg_cache = Path(os.environ.get("XDG_CACHE_HOME", home / ".cache"))

        if not self.config_dirs:
            self.config_dirs = [
                xdg_config / "lutris" / "games",
                xdg_data / "lutris" / "games",
            ]

        if not self.banner_dirs:
            self.banner_dirs = [
                xdg_data / "lutris" / "banners",
                xdg_cache / "lutris" / "banners",
            ]

        if not self.coverart_dirs:
            self.coverart_dirs = [
                xdg_data / "lutris" / "coverart",
                xdg_data / "lutris" / "covers",
                xdg_cache / "lutris" / "coverart",
            ]

        if not self.icon_dirs:
            self.icon_dirs = [
                xdg_data / "lutris" / "icons",
                xdg_cache / "lutris" / "icons",
                xdg_data / "icons" / "hicolor" / "128x128" / "apps",
                xdg_data / "icons" / "hicolor" / "256x256" / "apps",
                xdg_data / "icons" / "hicolor" / "scalable" / "apps",
                xdg_data / "icons" / "hicolor" / "48x48" / "apps",
                home / ".local" / "share" / "icons" / "hicolor" / "128x128" / "apps",
                Path("/usr/share/icons/hicolor/128x128/apps"),
                Path("/usr/share/icons/hicolor/scalable/apps"),
            ]

    def get_games(self) -> list[Game]:
        """Scan configured directories and return all discovered Lutris games.

        Returns:
            A list of Game instances discovered from Lutris YAML configuration files.
        """
        games: list[Game] = []
        seen_ids: set[str] = set()

        for config_dir in self.config_dirs:
            if not config_dir.is_dir():
                continue

            # Scan for both .yml and .yaml files in the directory
            yaml_files = sorted(
                list(config_dir.glob("*.yml")) + list(config_dir.glob("*.yaml")),
                key=lambda p: p.name,
            )

            for file_path in yaml_files:
                game = self.load_game_file(file_path)
                if game is not None and game.id not in seen_ids:
                    seen_ids.add(game.id)
                    games.append(game)

        return games

    def load_game_file(self, file_path: Path) -> Game | None:
        """Parse a single Lutris YAML configuration file into a Game model.

        Args:
            file_path: Path to the Lutris game YAML file.

        Returns:
            A Game instance if parsing succeeded, or None if the file is invalid.
        """
        try:
            with file_path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except (OSError, yaml.YAMLError):
            return None

        if not isinstance(data, dict):
            return None

        game_section = data.get("game")
        game_dict = game_section if isinstance(game_section, dict) else {}

        # Extract game name / title
        name = self._resolve_game_name(data, game_dict, file_path)

        # Extract slug and provider-specific application ID
        raw_slug = data.get("slug") or data.get("game_slug") or file_path.stem
        slug = str(raw_slug)

        game_slug = data.get("game_slug")
        game_slug_str = str(game_slug) if game_slug else None

        # Build unique identifier
        game_id = f"lutris_{file_path.stem}"

        # Resolve executable path
        executable = self._resolve_executable(game_dict)

        # Resolve cover art and icon
        cover = self._resolve_cover(slug, game_slug_str, file_path.stem)
        icon = self._resolve_icon(slug, game_slug_str, file_path.stem)

        # Determine installation state
        installed = True
        if executable is not None:
            installed = executable.exists()

        favorite = bool(data.get("favorite", False))

        return Game(
            id=game_id,
            name=name,
            source="lutris",
            launcher="lutris",
            executable=executable,
            icon=icon,
            cover=cover,
            installed=installed,
            favorite=favorite,
            appid=slug,
        )

    def _resolve_game_name(
        self,
        data: dict[str, Any],
        game_dict: dict[str, Any],
        file_path: Path,
    ) -> str:
        """Determine the human-readable display name of the game."""
        raw_name = data.get("name")
        if isinstance(raw_name, str) and raw_name.strip():
            return raw_name.strip()

        # If working_dir is set, check the directory name
        working_dir = game_dict.get("working_dir")
        if isinstance(working_dir, str) and working_dir.strip():
            dir_name = Path(working_dir).name.strip()
            if dir_name and not dir_name.startswith("."):
                return dir_name

        # Fallback to formatting game_slug or slug
        slug = data.get("game_slug") or data.get("slug")
        if isinstance(slug, str) and slug.strip():
            cleaned = re.sub(r"-\d+$", "", slug.strip())
            return cleaned.replace("-", " ").replace("_", " ").title()

        # Fallback to formatting filename stem
        cleaned_stem = re.sub(r"-\d+$", "", file_path.stem)
        return cleaned_stem.replace("-", " ").replace("_", " ").title()

    def _resolve_executable(self, game_dict: dict[str, Any]) -> Path | None:
        """Extract the executable or main file path from the game section."""
        exe = game_dict.get("exe") or game_dict.get("main_file")
        if isinstance(exe, str) and exe.strip():
            return Path(exe.strip())
        return None

    def _resolve_cover(
        self,
        slug: str,
        game_slug: str | None,
        file_stem: str,
    ) -> Path | None:
        """Find the game cover art or banner image path if present."""
        candidates = self._generate_asset_candidates(slug, game_slug, file_stem)
        extensions = (".jpg", ".png", ".webp", ".jpeg")

        search_dirs = list(self.coverart_dirs) + list(self.banner_dirs)

        for directory in search_dirs:
            if not directory.is_dir():
                continue
            for candidate in candidates:
                for ext in extensions:
                    target = directory / f"{candidate}{ext}"
                    if target.is_file():
                        return target

        return None

    def _resolve_icon(
        self,
        slug: str,
        game_slug: str | None,
        file_stem: str,
    ) -> Path | None:
        """Find the game icon path if present."""
        candidates = self._generate_asset_candidates(slug, game_slug, file_stem)
        extensions = (".png", ".svg", ".jpg", ".webp", ".ico")

        for directory in self.icon_dirs:
            if not directory.is_dir():
                continue
            for candidate in candidates:
                for prefix in ("lutris_", ""):
                    for ext in extensions:
                        target = directory / f"{prefix}{candidate}{ext}"
                        if target.is_file():
                            return target

        # If no standalone icon found, banner/cover can serve as visual representation
        return None

    def _generate_asset_candidates(
        self,
        slug: str,
        game_slug: str | None,
        file_stem: str,
    ) -> list[str]:
        """Generate potential asset file name stems."""
        candidates: list[str] = []

        def add_candidate(item: str | None) -> None:
            if not item:
                return
            cleaned = item.strip()
            if cleaned and cleaned not in candidates:
                candidates.append(cleaned)
            base = re.sub(r"-\d+$", "", cleaned)
            if base and base not in candidates:
                candidates.append(base)

        add_candidate(slug)
        add_candidate(game_slug)
        add_candidate(file_stem)

        return candidates


def get_games(config_dirs: list[Path] | None = None) -> list[Game]:
    """Retrieve all discovered Lutris games using the default or provided configuration paths.

    Args:
        config_dirs: Optional list of directories to scan for Lutris YAML files.

    Returns:
        A list of Game instances.
    """
    provider = LutrisProvider(config_dirs=config_dirs or [])
    return provider.get_games()
