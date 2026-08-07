"""Steam game provider for GameDeck."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import vdf

from gamedeck.models import Game

__all__ = ["SteamProvider", "get_games"]

logger = logging.getLogger(__name__)

# Known Steam runtime components, compatibility tools, dedicated servers, and redistributables
KNOWN_RUNTIME_APPIDS: frozenset[str] = frozenset(
    {
        "228980",  # Steamworks Common Redistributables
        "250820",  # SteamVR
        "891390",  # Steam Linux Runtime
        "1070560",  # Steam Linux Runtime 1.0 (scout)
        "1391110",  # Steam Linux Runtime 2.0 (soldier)
        "1628350",  # Steam Linux Runtime 3.0 (sniper)
        "4183110",  # Steam Linux Runtime 4.0
        "1493710",  # Proton Experimental
        "2805730",  # Proton Hotfix
        "2230260",  # Proton 9.0
        "1580130",  # Proton 8.0
        "1245040",  # Proton 7.0
        "1113280",  # Proton 6.3
        "1054830",  # Proton 5.13
        "961940",  # Proton 5.0
        "858280",  # Proton 4.11
        "2180100",  # Proton Next
        "1887720",  # Proton EasyAntiCheat Runtime
        "1826330",  # Proton BattlEye Runtime
        "211",  # Source SDK Base 2006
        "212",  # Source SDK Base 2007
        "213",  # Source SDK Base Singleplayer
        "214",  # Source SDK Base Multiplayer
        "215",  # Source SDK Base 2013 Singleplayer
        "218",  # Source SDK Base 2013 Multiplayer
    }
)


@dataclass(slots=True)
class SteamProvider:
    """Provider for scanning and discovering installed Steam games.

    Reads Steam `libraryfolders.vdf` to detect all configured Steam library
    locations, parses individual `appmanifest_*.acf` files, and returns
    `Game` model instances while filtering out Steam runtimes, compatibility tools,
    dedicated servers, and non-game packages.

    Attributes:
        steam_roots: Base Steam installation directories to scan.
    """

    steam_roots: list[Path] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Discover default Steam installation roots if none were provided."""
        if not self.steam_roots:
            home = Path.home()
            xdg_data = Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share"))

            candidates = [
                xdg_data / "Steam",
                home / ".steam" / "steam",
                home / ".steam" / "root",
                home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam",
                home / ".var" / "app" / "com.valvesoftware.Steam" / ".steam" / "steam",
                home / "snap" / "steam" / "common" / ".local" / "share" / "Steam",
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

            self.steam_roots = resolved_roots

    def get_games(self) -> list[Game]:
        """Scan all Steam libraries and return a list of discovered games.

        Returns:
            A list of Game model instances for all installed real playable Steam games.
        """
        games: list[Game] = []
        seen_ids: set[str] = set()

        libraries = self.find_library_folders()

        for steamapps_dir in libraries:
            if not steamapps_dir.is_dir():
                continue

            manifest_files = sorted(steamapps_dir.glob("appmanifest_*.acf"), key=lambda p: p.name)

            for manifest_path in manifest_files:
                try:
                    game = self.parse_manifest(manifest_path, steamapps_dir)
                    if game is not None and game.id not in seen_ids:
                        seen_ids.add(game.id)
                        games.append(game)
                except Exception as err:
                    logger.warning("Failed to parse Steam manifest '%s': %s", manifest_path, err)

        logger.debug("Steam provider discovered %d games across %d libraries", len(games), len(libraries))
        return games

    def find_library_folders(self) -> list[Path]:
        """Parse `libraryfolders.vdf` from each Steam root to find all library folders.

        Returns:
            A list of Paths pointing to valid `steamapps` directories across all libraries.
        """
        libraries: list[Path] = []
        seen_dirs: set[Path] = set()

        for root in self.steam_roots:
            if not root.is_dir():
                continue

            # Always check root's own steamapps folder
            root_steamapps = root / "steamapps"
            if root_steamapps.is_dir():
                try:
                    resolved_root_sa = root_steamapps.resolve()
                except OSError:
                    resolved_root_sa = root_steamapps
                if resolved_root_sa not in seen_dirs:
                    seen_dirs.add(resolved_root_sa)
                    libraries.append(root_steamapps)

            # Check libraryfolders.vdf locations
            vdf_candidates = [
                root / "steamapps" / "libraryfolders.vdf",
                root / "config" / "libraryfolders.vdf",
            ]

            for vdf_file in vdf_candidates:
                if not vdf_file.is_file():
                    continue

                try:
                    with vdf_file.open("r", encoding="utf-8", errors="replace") as f:
                        data = vdf.load(f)
                except (OSError, vdf.VDFError, Exception) as err:
                    logger.debug("Skipping unreadable Steam VDF '%s': %s", vdf_file, err)
                    continue

                if not isinstance(data, dict):
                    continue

                self._extract_libraries_from_vdf(data, libraries, seen_dirs)

        return libraries

    def parse_manifest(self, manifest_path: Path, steamapps_dir: Path) -> Game | None:
        """Parse an `appmanifest_*.acf` file into a Game model instance.

        Args:
            manifest_path: Path to the appmanifest file.
            steamapps_dir: The parent steamapps directory of the manifest.

        Returns:
            A Game instance if valid and not a runtime/tool/server component, else None.
        """
        try:
            with manifest_path.open("r", encoding="utf-8", errors="replace") as f:
                data = vdf.load(f)
        except (OSError, vdf.VDFError, Exception) as err:
            logger.debug("Skipping unreadable manifest '%s': %s", manifest_path, err)
            return None

        if not isinstance(data, dict):
            return None

        # Manifest data is wrapped under AppState or at top-level
        app_state = data.get("AppState")
        app_dict: dict[str, Any] = app_state if isinstance(app_state, dict) else data

        # Extract app ID
        raw_appid = app_dict.get("appid")
        if raw_appid is not None and str(raw_appid).strip():
            appid = str(raw_appid).strip()
        else:
            # Fallback to extracting from filename: appmanifest_<appid>.acf
            stem = manifest_path.stem
            appid = stem.split("_", 1)[1] if "_" in stem else stem

        # Extract game title
        name = str(app_dict.get("name", "")).strip()

        # Extract installation directory name
        installdir = str(app_dict.get("installdir", "")).strip()

        # Filter out runtimes, compatibility tools, dedicated servers, and packages
        if self._is_runtime_component(appid, name, installdir):
            return None

        # Build unique identifier
        game_id = f"steam_{appid}"

        # Resolve executable or common directory
        executable: Path | None = None
        if installdir:
            common_dir = steamapps_dir / "common" / installdir
            if common_dir.exists():
                executable = common_dir

        # Determine installation status via StateFlags (StateFlag 4 = Fully Installed)
        installed = True
        state_flags = app_dict.get("StateFlags")
        if state_flags is not None:
            try:
                flags_int = int(state_flags)
                # StateFlag 4 indicates StateFullyInstalled
                installed = bool(flags_int & 4)
            except (ValueError, TypeError):
                installed = executable.exists() if executable else True
        elif executable is not None:
            installed = executable.exists()

        # Resolve cover art and icon
        cover = self._resolve_cover(appid)
        icon = self._resolve_icon(appid)

        return Game(
            id=game_id,
            name=name,
            source="steam",
            launcher="steam",
            executable=executable,
            icon=icon,
            cover=cover,
            installed=installed,
            favorite=False,
            appid=appid,
        )

    def _is_runtime_component(self, appid: str, name: str, installdir: str) -> bool:
        """Check if an application represents a runtime, server, compatibility tool, or non-game package."""
        if not name or not name.strip():
            return True

        if appid in KNOWN_RUNTIME_APPIDS:
            return True

        name_lower = name.lower().strip()
        installdir_lower = installdir.lower().strip()

        # 1. Proton and Compatibility Tools
        if (
            name_lower == "proton"
            or name_lower.startswith("proton ")
            or "proton -" in name_lower
            or "proton experimental" in name_lower
            or "proton hotfix" in name_lower
            or name_lower.endswith(" proton")
            or "ge-proton" in name_lower
            or "luxtorpeda" in name_lower
            or "boxtron" in name_lower
            or "roberta" in name_lower
            or "compatibility tool" in name_lower
            or "compatibility data" in name_lower
            or installdir_lower.startswith("proton")
            or installdir_lower.startswith("ge-proton")
        ):
            return True

        # 2. Steam Linux Runtime and Runtime Packages
        if (
            "steam linux runtime" in name_lower
            or "steamlinuxruntime" in installdir_lower
            or "steam runtime" in name_lower
            or "steam_runtime" in installdir_lower
            or name_lower.startswith("steam linux runtime")
            or name_lower.startswith("steam runtime")
        ):
            return True

        # 3. Steamworks Common Redistributables and Shared SDKs
        if (
            "steamworks common redistributables" in name_lower
            or "steamworks shared" in installdir_lower
            or "common redistributables" in name_lower
            or "steamworks sdk" in name_lower
            or "source sdk" in name_lower
            or "source sdk base" in name_lower
            or installdir_lower.startswith("source sdk")
        ):
            return True

        # 4. Dedicated Servers
        if (
            "dedicated server" in name_lower
            or "dedicated server" in installdir_lower
            or name_lower.endswith(" dedicated server")
            or name_lower.endswith(" server")
            or installdir_lower.endswith("_server")
            or installdir_lower.endswith(" server")
        ):
            return True

        # 5. Anti-Cheat and VR Runtimes
        if (
            "easyanticheat" in name_lower
            or "easy anti-cheat" in name_lower
            or "battleye" in name_lower
            or "eac_server" in name_lower
            or "steamvr" in name_lower
            or name_lower.startswith("steamvr")
            or "steam vr" in name_lower
            or installdir_lower.startswith("steamvr")
        ):
            return True

        # 6. Tools, Editors, Benchmarks, Soundtracks
        if (
            name_lower.startswith("steam client")
            or name_lower.startswith("directx")
            or name_lower.startswith("vulkan run time")
            or name_lower.startswith("microsoft visual c++")
            or name_lower.endswith(" benchmark")
            or "creation kit" in name_lower
            or "redmod" in name_lower
            or " soundtrack" in name_lower
            or " original soundtrack" in name_lower
            or name_lower.endswith(" ost")
            or " bonus content" in name_lower
            or " artbook" in name_lower
        ):
            return True

        return False

    def _extract_libraries_from_vdf(
        self,
        data: dict[str, Any],
        libraries: list[Path],
        seen_dirs: set[Path],
    ) -> None:
        """Extract library directory paths from a parsed libraryfolders.vdf structure."""
        top_section = data.get("libraryfolders") or data.get("LibraryFolders") or data

        if not isinstance(top_section, dict):
            return

        for key, val in top_section.items():
            target_path: Path | None = None

            if isinstance(val, dict) and "path" in val:
                target_path = Path(str(val["path"]))
            elif isinstance(val, str) and val.strip() and key.isdigit():
                target_path = Path(val.strip())

            if target_path is None:
                continue

            # Resolve to steamapps folder within the library
            candidate_steamapps = (
                target_path / "steamapps"
                if (target_path / "steamapps").is_dir()
                else target_path
            )

            if candidate_steamapps.is_dir():
                try:
                    resolved = candidate_steamapps.resolve()
                except OSError:
                    resolved = candidate_steamapps

                if resolved not in seen_dirs:
                    seen_dirs.add(resolved)
                    libraries.append(candidate_steamapps)

    def _resolve_cover(self, appid: str) -> Path | None:
        """Find the cover art or capsule image for a Steam game."""
        for root in self.steam_roots:
            # 1. Check Steam appcache librarycache (600x900 portrait capsule)
            cache_dir = root / "appcache" / "librarycache" / appid
            if cache_dir.is_dir():
                candidates = [
                    cache_dir / f"{appid}_library_600x900.jpg",
                    cache_dir / "library_600x900.jpg",
                    cache_dir / f"{appid}_library_hero.jpg",
                    cache_dir / "library_hero.jpg",
                    cache_dir / f"{appid}_header.jpg",
                    cache_dir / "header.jpg",
                ]
                for candidate in candidates:
                    if candidate.is_file():
                        return candidate

                # Fallback to any image inside the appcache folder
                for img in cache_dir.glob("*.jpg"):
                    if img.is_file():
                        return img
                for img in cache_dir.glob("*.png"):
                    if img.is_file():
                        return img

            # 2. Check userdata grid folders
            userdata_dir = root / "userdata"
            if userdata_dir.is_dir():
                try:
                    user_dirs = list(userdata_dir.iterdir())
                except OSError:
                    continue

                for user_dir in user_dirs:
                    if not user_dir.is_dir():
                        continue
                    grid_dir = user_dir / "config" / "grid"
                    if not grid_dir.is_dir():
                        continue

                    grid_candidates = [
                        grid_dir / f"{appid}p.jpg",
                        grid_dir / f"{appid}p.png",
                        grid_dir / f"{appid}.jpg",
                        grid_dir / f"{appid}.png",
                        grid_dir / f"{appid}_hero.jpg",
                    ]
                    for candidate in grid_candidates:
                        if candidate.is_file():
                            return candidate

        return None

    def _resolve_icon(self, appid: str) -> Path | None:
        """Find the icon file for a Steam game."""
        home = Path.home()
        xdg_data = Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share"))

        # 1. Check system hicolor icon themes
        icon_dirs = [
            xdg_data / "icons" / "hicolor" / "128x128" / "apps",
            xdg_data / "icons" / "hicolor" / "256x256" / "apps",
            xdg_data / "icons" / "hicolor" / "scalable" / "apps",
            xdg_data / "icons" / "hicolor" / "48x48" / "apps",
            xdg_data / "icons" / "hicolor" / "32x32" / "apps",
            home / ".local" / "share" / "icons" / "hicolor" / "128x128" / "apps",
            Path("/usr/share/icons/hicolor/128x128/apps"),
            Path("/usr/share/icons/hicolor/scalable/apps"),
        ]

        for icon_dir in icon_dirs:
            if not icon_dir.is_dir():
                continue
            for ext in (".png", ".svg"):
                icon_file = icon_dir / f"steam_icon_{appid}{ext}"
                if icon_file.is_file():
                    return icon_file

        # 2. Check Steam appcache librarycache logo/icon
        for root in self.steam_roots:
            cache_dir = root / "appcache" / "librarycache" / appid
            if cache_dir.is_dir():
                candidates = [
                    cache_dir / f"{appid}_icon.jpg",
                    cache_dir / f"{appid}_icon.png",
                    cache_dir / f"{appid}_logo.png",
                    cache_dir / "logo.png",
                    cache_dir / "icon.png",
                ]
                for candidate in candidates:
                    if candidate.is_file():
                        return candidate

        return None


def get_games(steam_roots: list[Path] | None = None) -> list[Game]:
    """Retrieve all discovered Steam games across all libraries.

    Args:
        steam_roots: Optional list of base Steam installation directories.

    Returns:
        A list of Game model instances.
    """
    provider = SteamProvider(steam_roots=steam_roots or [])
    return provider.get_games()
