"""Filesystem game provider for GameDeck."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from gamedeck.models import Game

__all__ = ["FilesystemProvider", "get_games"]

logger = logging.getLogger(__name__)

# Ignored directory names containing redistributables, tools, or Wine system prefixes
IGNORED_SUBDIR_NAMES: frozenset[str] = frozenset(
    {
        "_redist",
        "redist",
        "redistributables",
        "_commonredist",
        "commonredist",
        "support",
        "prerequisites",
        "directx",
        "vcredist",
        "dotnet",
        "dependencies",
        "system32",
        "syswow64",
        "dosdevices",
        "umu",
        "umu-default",
        "pfx",
        "wineprefix",
    }
)

# Windows system binaries and Wine internal utilities to ignore
WINDOWS_SYSTEM_EXES: frozenset[str] = frozenset(
    {
        "regedit",
        "explorer",
        "notepad",
        "cmd",
        "rundll32",
        "control",
        "msiexec",
        "svchost",
        "dxdiag",
        "iexplore",
        "wscript",
        "cscript",
        "winhlp32",
        "hh",
        "start",
        "wineboot",
        "winepath",
        "winecfg",
        "winemenubuilder",
        "services",
        "rpcss",
        "plugplay",
        "conhost",
        "ipconfig",
        "taskmgr",
        "taskkill",
        "attrib",
        "xcopy",
        "robocopy",
        "chcp",
        "reg",
        "ping",
        "net",
        "netstat",
        "wmic",
        "powershell",
        "pwsh",
    }
)

# Executable filename patterns to ignore (uninstallers, redistributables, helpers, crash reporters)
IGNORED_EXE_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Uninstallers and clean-up tools
    re.compile(r"^unins\w*", re.IGNORECASE),
    re.compile(r"uninstall", re.IGNORECASE),
    re.compile(r"cleanup", re.IGNORECASE),
    # Redistributables and installers
    re.compile(r"^vc_?redist", re.IGNORECASE),
    re.compile(r"^vcredist", re.IGNORECASE),
    re.compile(r"^dx(web)?setup", re.IGNORECASE),
    re.compile(r"^directx", re.IGNORECASE),
    re.compile(r"^ndp\w*", re.IGNORECASE),
    re.compile(r"^dotnet", re.IGNORECASE),
    re.compile(r"^oalinst", re.IGNORECASE),
    re.compile(r"^physx", re.IGNORECASE),
    re.compile(r"^vulkan", re.IGNORECASE),
    re.compile(r"^openal", re.IGNORECASE),
    re.compile(r"installer", re.IGNORECASE),
    re.compile(r"prereq", re.IGNORECASE),
    # Crash reporters, diagnostics, and web helpers
    re.compile(r"crashreport(client)?", re.IGNORECASE),
    re.compile(r"crashhandler", re.IGNORECASE),
    re.compile(r"unitycrashhandler", re.IGNORECASE),
    re.compile(r"werfault", re.IGNORECASE),
    re.compile(r"epicwebhelper", re.IGNORECASE),
    re.compile(r"cefprocess", re.IGNORECASE),
    re.compile(r"browserprocess", re.IGNORECASE),
    # Anti-cheat and third-party overlays
    re.compile(r"easyanticheat", re.IGNORECASE),
    re.compile(r"battleye", re.IGNORECASE),
    re.compile(r"eac_server", re.IGNORECASE),
    # Trainers, patchers, and standalone updaters
    re.compile(r"trainer", re.IGNORECASE),
    re.compile(r"patcher", re.IGNORECASE),
    re.compile(r"^updater?\.exe$", re.IGNORECASE),
)


@dataclass(slots=True)
class FilesystemProvider:
    """Provider for scanning local directory trees for standalone Windows and native games.

    Detects Windows game executables (.exe) while filtering out uninstallers,
    redistributables, engine crash reporters, and installer tools.

    Attributes:
        search_dirs: List of root directories to scan for installed game folders.
        max_depth: Maximum directory recursion depth when locating game executables.
    """

    search_dirs: list[Path] = field(default_factory=list)
    max_depth: int = 4

    def __post_init__(self) -> None:
        """Initialize standard game search directories if none were specified."""
        if not self.search_dirs:
            home = Path.home()
            candidates = [
                home / "Games",
                Path("/mnt/windows/Games"),
                Path("/mnt/games"),
                home / ".wine" / "drive_c" / "Program Files",
                home / ".wine" / "drive_c" / "Program Files (x86)",
                home / "Games" / "Heroic",
                home / "Games" / "Epic Games",
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

            self.search_dirs = resolved_dirs

    def get_games(self) -> list[Game]:
        """Scan all configured directories and return discovered games.

        Returns:
            A list of Game model instances for each detected game.
        """
        games: list[Game] = []
        seen_ids: set[str] = set()

        for search_dir in self.search_dirs:
            if not search_dir.is_dir():
                continue

            # Iterate over subdirectories within the search root
            try:
                subdirs = sorted(
                    [p for p in search_dir.iterdir() if p.is_dir() and not p.name.startswith(".")],
                    key=lambda p: p.name.lower(),
                )
            except OSError as err:
                logger.debug("Skipping unreadable search directory '%s': %s", search_dir, err)
                continue

            for game_dir in subdirs:
                if game_dir.name.lower() in IGNORED_SUBDIR_NAMES:
                    continue

                exe = self.find_game_executable(game_dir)
                if exe is not None:
                    game = self._build_game_from_dir(game_dir, exe)
                    if game.id not in seen_ids:
                        seen_ids.add(game.id)
                        games.append(game)

            # If search_dir itself has immediate game executables and is a standalone game folder
            if not subdirs:
                exe = self.find_game_executable(search_dir)
                if exe is not None:
                    game = self._build_game_from_dir(search_dir, exe)
                    if game.id not in seen_ids:
                        seen_ids.add(game.id)
                        games.append(game)

        logger.debug("Filesystem provider discovered %d games across %d search dirs", len(games), len(self.search_dirs))
        return games

    def find_game_executable(self, game_dir: Path) -> Path | None:
        """Locate the best primary game executable within a game directory.

        Args:
            game_dir: Directory containing game files.

        Returns:
            Path to the most suitable game executable, or None if no valid game executable found.
        """
        if not game_dir.is_dir():
            return None

        candidates: list[Path] = []
        self._collect_executables(game_dir, game_dir, 0, candidates)

        valid_candidates = [exe for exe in candidates if not self.is_ignored_executable(exe, game_dir)]
        if not valid_candidates:
            return None

        return self._rank_best_executable(valid_candidates, game_dir)

    def is_ignored_executable(self, path: Path, game_dir: Path | None = None) -> bool:
        """Check if an executable matches uninstaller, redistributable, or tool patterns.

        Args:
            path: Path to the executable file.
            game_dir: Optional root game directory for relative path component validation.

        Returns:
            True if the file should be ignored, False if it is a valid game candidate.
        """
        stem_lower = path.stem.lower()
        filename = path.name.lower()

        # Check against Windows system and Wine utilities
        if stem_lower in WINDOWS_SYSTEM_EXES:
            return True

        # Check relative directory path components for redistributables
        if game_dir is not None:
            try:
                rel = path.relative_to(game_dir)
                for part in rel.parts[:-1]:
                    if part.lower() in IGNORED_SUBDIR_NAMES:
                        return True
            except ValueError:
                pass
        else:
            # Check immediate parent folder name
            if path.parent.name.lower() in IGNORED_SUBDIR_NAMES:
                return True

        # Check filename against regex patterns
        for pattern in IGNORED_EXE_PATTERNS:
            if pattern.search(filename):
                return True

        return False

    def _collect_executables(
        self,
        current_dir: Path,
        game_root: Path,
        current_depth: int,
        results: list[Path],
    ) -> None:
        """Recursively collect .exe files up to max_depth."""
        if current_depth > self.max_depth:
            return

        try:
            entries = list(current_dir.iterdir())
        except OSError:
            return

        for entry in entries:
            if entry.name.startswith("."):
                continue

            if entry.is_dir():
                if entry.name.lower() in IGNORED_SUBDIR_NAMES:
                    continue
                self._collect_executables(entry, game_root, current_depth + 1, results)
            elif entry.is_file() and entry.suffix.lower() == ".exe":
                results.append(entry)

    def _rank_best_executable(self, candidates: list[Path], game_dir: Path) -> Path:
        """Rank candidate executables and select the primary game binary."""
        dir_clean = self._normalize_slug(game_dir.name)

        def score(exe: Path) -> tuple[int, int]:
            points = 0
            stem_lower = exe.stem.lower()
            stem_clean = self._normalize_slug(exe.stem)

            # High score for shipping / main binary suffixes
            if stem_lower.endswith("-win64-shipping") or stem_lower.endswith("_shipping"):
                points += 100
            elif "shipping" in stem_lower:
                points += 80

            # Match between folder name and executable name
            if stem_clean == dir_clean:
                points += 90
            elif stem_clean in dir_clean or dir_clean in stem_clean:
                points += 60

            # Favor binaries in Binaries/Win64 or bin directories
            parts_lower = [p.lower() for p in exe.parts]
            if "win64" in parts_lower or "x64" in parts_lower:
                points += 40
            if "binaries" in parts_lower or "bin" in parts_lower:
                points += 30

            # Root-level executable preference if name is relevant
            if exe.parent == game_dir:
                points += 20

            # Larger files are more likely to be full game binaries than small launch stubs
            file_size = 0
            try:
                file_size = exe.stat().st_size
            except OSError:
                pass

            return (points, file_size)

        sorted_candidates = sorted(candidates, key=score, reverse=True)
        return sorted_candidates[0]

    def _build_game_from_dir(self, game_dir: Path, executable: Path) -> Game:
        """Build a Game model instance for a verified game directory."""
        raw_name = game_dir.name.strip()
        slug = self._normalize_slug(raw_name) or "game"
        game_id = f"filesystem_{slug}"

        cover, icon = self._resolve_assets(game_dir, slug)

        return Game(
            id=game_id,
            name=raw_name,
            source="filesystem",
            launcher="wine",
            executable=executable,
            icon=icon,
            cover=cover,
            installed=executable.exists(),
            favorite=False,
            appid=slug,
        )

    def _resolve_assets(self, game_dir: Path, slug: str) -> tuple[Path | None, Path | None]:
        """Locate cover art and icon files for the game."""
        cover: Path | None = None
        icon: Path | None = None

        cover_names = {"cover", "poster", "banner", "capsule", "folder", slug}
        icon_names = {"icon", "app", slug, f"lutris_{slug}"}

        image_exts = {".jpg", ".jpeg", ".png", ".webp"}
        icon_exts = {".ico", ".png", ".svg"}

        # 1. Search inside game folder
        try:
            for item in game_dir.iterdir():
                if not item.is_file():
                    continue
                stem_lower = item.stem.lower()
                suffix_lower = item.suffix.lower()

                if cover is None and stem_lower in cover_names and suffix_lower in image_exts:
                    cover = item
                if icon is None and stem_lower in icon_names and suffix_lower in icon_exts:
                    icon = item
        except OSError:
            pass

        # 2. Check local Lutris artwork caches as fallback
        if cover is None or icon is None:
            home = Path.home()
            xdg_data = Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share"))

            if cover is None:
                for art_dir in (xdg_data / "lutris" / "coverart", xdg_data / "lutris" / "banners"):
                    if not art_dir.is_dir():
                        continue
                    for ext in (".jpg", ".png", ".webp"):
                        art_file = art_dir / f"{slug}{ext}"
                        if art_file.is_file():
                            cover = art_file
                            break
                    if cover is not None:
                        break

            if icon is None:
                for icon_dir in (
                    xdg_data / "icons" / "hicolor" / "128x128" / "apps",
                    xdg_data / "icons" / "hicolor" / "scalable" / "apps",
                    xdg_data / "lutris" / "icons",
                ):
                    if not icon_dir.is_dir():
                        continue
                    for prefix in ("lutris_", ""):
                        for ext in (".png", ".svg"):
                            icon_file = icon_dir / f"{prefix}{slug}{ext}"
                            if icon_file.is_file():
                                icon = icon_file
                                break
                        if icon is not None:
                            break
                    if icon is not None:
                        break

        return cover, icon

    def _normalize_slug(self, text: str) -> str:
        """Convert a name to a clean alphanumeric slug."""
        lowered = text.lower()
        cleaned = re.sub(r"[^a-z0-9]+", "-", lowered)
        return cleaned.strip("-")


def get_games(search_dirs: list[Path] | None = None) -> list[Game]:
    """Discover all games across the provided or default filesystem search paths.

    Args:
        search_dirs: Optional list of root directories to scan.

    Returns:
        A list of Game model instances.
    """
    provider = FilesystemProvider(search_dirs=search_dirs or [])
    return provider.get_games()
