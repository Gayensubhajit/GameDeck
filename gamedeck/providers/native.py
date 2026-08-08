"""Native Linux game provider for GameDeck scanning desktop entries."""

from __future__ import annotations

import configparser
import logging
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gamedeck.models import Game
from gamedeck.providers import BaseProvider

__all__ = ["NativeProvider", "get_games"]

logger = logging.getLogger(__name__)

# Launcher backends, emulators, engines, and utilities to ignore
IGNORED_DESKTOP_IDS: frozenset[str] = frozenset(
    {
        # Game Store Launchers and Managers
        "steam",
        "com.valvesoftware.steam",
        "net.lutris.lutris",
        "lutris",
        "heroic",
        "com.heroicgameslauncher.hgl",
        "com.usebottles.bottles",
        "bottles",
        "io.github.sharkwouter.minigalaxy",
        "minigalaxy",
        "io.itch.itch",
        "itch",
        "gamehub",
        "gog-galaxy",
        "minecraft-launcher",
        "com.mojang.minecraft",
        "playonlinux",
        # Emulators and Frontends
        "com.libretro.retroarch",
        "retroarch",
        "dosbox",
        "scummvm",
        "rpcs3",
        "pcsx2",
        "dolphin-emu",
        "yuzu",
        "ryujinx",
        "cemu",
        "duckstation",
        "ppsspp",
        "mame",
        # Generic Engines & Frameworks without game payload
        "love",
        # Game utilities, overlays, and performance tools
        "steamtinkerlaunch",
        "io.github.antimicrox.antimicrox",
        "antimicrox",
        "antimicro",
        "io.github.benjamimgois.goverlay",
        "goverlay",
        "mangohud",
        "gamemode",
        "gamemoderun",
        "protontricks",
        "winetricks",
        "vkbasalt",
        "input-remapper",
        "input-remapper-gtk",
        "sc-controller",
        "wine",
        "winecfg",
    }
)


@dataclass(slots=True)
class NativeProvider(BaseProvider):
    """Provider for scanning native Linux games from standard `.desktop` application entries.

    Scans system and user desktop application directories, filters for entries with
    ``Category=Game`` (or ``Categories=...Game...``), and ignores external launchers,
    emulators, and system utilities.

    Class attributes:
        name: Provider identifier — ``"native"``.
        priority: Deduplication precedence — ``20``.

    Attributes:
        app_dirs: List of directories to scan for `.desktop` application entries.
    """

    name: str = field(default="native", init=False, repr=False, compare=False)
    priority: int = field(default=20, init=False, repr=False, compare=False)

    app_dirs: list[Path] = field(default_factory=list)

    def enabled(self) -> bool:
        """Return ``True`` if at least one application directory exists.

        When no app_dirs were provided at construction, auto-discovery runs first.
        Explicitly-provided app_dirs are used as-is.
        """
        if not self.app_dirs:
            self.__post_init__()
        return any(d.is_dir() for d in self.app_dirs)

    def __post_init__(self) -> None:
        """Initialize standard application search directories if none were provided."""
        if not self.app_dirs:
            home = Path.home()
            xdg_data = Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share"))

            candidates = [
                Path("/usr/share/applications"),
                home / ".local" / "share" / "applications",
                xdg_data / "applications",
                Path("/usr/local/share/applications"),
                Path("/var/lib/flatpak/exports/share/applications"),
                home / ".local" / "share" / "flatpak" / "exports" / "share" / "applications",
            ]

            resolved_dirs: list[Path] = []
            seen: set[Path] = set()

            for candidate in candidates:
                if candidate.is_dir():
                    try:
                        resolved = candidate.resolve()
                    except OSError:
                        resolved = candidate
                    if resolved not in seen:
                        seen.add(resolved)
                        resolved_dirs.append(resolved)

            self.app_dirs = resolved_dirs

    def scan(self) -> list[Game]:
        """Scan configured desktop application directories and return discovered native games.

        Returns:
            A list of Game instances for all discovered native Linux games.
        """
        games: list[Game] = []
        seen_ids: set[str] = set()

        for app_dir in self.app_dirs:
            if not app_dir.is_dir():
                continue

            desktop_files = sorted(app_dir.glob("*.desktop"), key=lambda p: p.name.lower())

            for desktop_path in desktop_files:
                try:
                    game = self.parse_desktop_file(desktop_path)
                    if game is not None and game.id not in seen_ids:
                        seen_ids.add(game.id)
                        games.append(game)
                except Exception as err:
                    logger.warning("Failed to parse desktop file '%s': %s", desktop_path, err)

        logger.debug("Native provider discovered %d games across %d app dirs", len(games), len(self.app_dirs))
        return games

    def parse_desktop_file(self, desktop_path: Path) -> Game | None:
        """Parse an XDG `.desktop` file into a Game model instance.

        Args:
            desktop_path: Path to the `.desktop` file.

        Returns:
            A Game instance if the entry represents a valid native game, else None.
        """
        if self.is_ignored_desktop_file(desktop_path):
            return None

        # Parse desktop INI structure
        cfg = configparser.ConfigParser(interpolation=None, strict=False)
        try:
            cfg.read(desktop_path, encoding="utf-8")
        except (OSError, configparser.Error) as err:
            logger.debug("Skipping unreadable desktop file '%s': %s", desktop_path, err)
            return None

        if "Desktop Entry" not in cfg:
            return None

        entry = cfg["Desktop Entry"]

        # Validate entry type (must be Application if specified)
        entry_type = entry.get("Type", "Application").strip()
        if entry_type.lower() != "application":
            return None

        # Check visibility
        if entry.get("NoDisplay", "false").strip().lower() == "true":
            return None
        if entry.get("Hidden", "false").strip().lower() == "true":
            return None

        # Check category (must include Game)
        categories = entry.get("Categories", "")
        if not self._is_game_category(categories):
            return None

        # Extract game title
        raw_name = entry.get("Name", "").strip()
        if not raw_name:
            return None

        # Extract and clean executable command
        raw_exec = entry.get("Exec", "").strip()
        if not raw_exec:
            return None

        executable_path = self._resolve_executable_path(raw_exec)
        if executable_path is None:
            # Fallback to resolving the binary in PATH
            binary_name = self._extract_binary_name(raw_exec)
            if binary_name:
                found_bin = shutil.which(binary_name)
                if found_bin is not None:
                    executable_path = Path(found_bin)

        # Build clean desktop slug identifier
        stem = desktop_path.stem
        game_id = f"native_{stem}"

        # Discover native application icon from desktop Icon= field or stem
        icon_field = entry.get("Icon", "").strip()
        icon_path = self._resolve_desktop_icon(icon_field, stem)

        return Game(
            id=game_id,
            name=raw_name,
            source="native",
            launcher="native",
            executable=executable_path,
            icon=icon_path,
            cover=None,
            installed=True,
            favorite=False,
            appid=stem,
        )

    def is_ignored_desktop_file(self, desktop_path: Path) -> bool:
        """Check if a desktop entry belongs to an external launcher, emulator, or tool."""
        stem_lower = desktop_path.stem.lower()

        if stem_lower in IGNORED_DESKTOP_IDS:
            return True

        # Check prefix/suffix patterns (e.g. skin editors, level editors, server tools)
        if (
            "skineditor" in stem_lower
            or "editor" in stem_lower
            or stem_lower.endswith("-editor")
            or stem_lower.endswith("_editor")
            or "benchmark" in stem_lower
            or "server" in stem_lower
            or stem_lower.startswith("steam_")
            or stem_lower.startswith("lutris_")
            or stem_lower.startswith("heroic_")
        ):
            return True

        return False

    def _resolve_desktop_icon(self, icon_field: str, stem: str) -> Path | None:
        """Resolve icon path from desktop Icon= field or stem."""
        icon_name = icon_field or stem
        if not icon_name:
            return None

        # Check if icon_name is an absolute file path
        if icon_name.startswith("/"):
            p = Path(icon_name)
            if p.is_file() and p.stat().st_size > 0:
                return p

        home = Path.home()
        xdg_data = Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share"))
        icon_dirs = [
            xdg_data / "icons" / "hicolor" / "128x128" / "apps",
            xdg_data / "icons" / "hicolor" / "256x256" / "apps",
            xdg_data / "icons" / "hicolor" / "scalable" / "apps",
            xdg_data / "icons" / "hicolor" / "64x64" / "apps",
            xdg_data / "icons" / "hicolor" / "48x48" / "apps",
            home / ".local" / "share" / "icons" / "hicolor" / "128x128" / "apps",
            Path("/usr/share/icons/hicolor/128x128/apps"),
            Path("/usr/share/icons/hicolor/256x256/apps"),
            Path("/usr/share/icons/hicolor/64x64/apps"),
            Path("/usr/share/icons/hicolor/48x48/apps"),
            Path("/usr/share/icons/hicolor/scalable/apps"),
            Path("/usr/share/pixmaps"),
        ]

        for d in icon_dirs:
            if not d.is_dir():
                continue
            for ext in (".png", ".svg", ".xpm", ".ico"):
                candidate = d / f"{icon_name}{ext}"
                if candidate.is_file() and candidate.stat().st_size > 0:
                    return candidate

        return None

    def _is_game_category(self, categories_str: str) -> bool:
        """Check if Categories contains Game (e.g. Categories=Game;ActionGame;)."""
        if not categories_str:
            return False
        cats = [c.strip().lower() for c in categories_str.split(";") if c.strip()]
        return "game" in cats

    def _extract_binary_name(self, exec_str: str) -> str:
        """Extract the first word / binary token from an Exec= line."""
        tokens = exec_str.split()
        if not tokens:
            return ""
        return tokens[0].strip()

    def _resolve_executable_path(self, exec_str: str) -> Path | None:
        """Clean field codes (%f, %u, %c, etc.) and resolve executable file path."""
        # Strip field codes
        cleaned = re.sub(r"%[a-zA-Z]", "", exec_str).strip()
        tokens = cleaned.split()
        if not tokens:
            return None

        first_token = tokens[0].strip()
        bin_path = Path(first_token)

        if bin_path.is_file():
            return bin_path

        found = shutil.which(first_token)
        if found is not None:
            return Path(found)

        return None


def get_games(app_dirs: list[Path] | None = None) -> list[Game]:
    """Retrieve all native Linux games discovered from desktop application files.

    Args:
        app_dirs: Optional list of application directories to scan.

    Returns:
        A list of Game model instances.
    """
    provider = NativeProvider(app_dirs=app_dirs or [])
    return provider.get_games()
