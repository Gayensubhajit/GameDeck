"""Auto-discovery engine for GameDeck discovering Steam libraries, Wine prefixes, and mounted drives."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "DiscoveredSource",
    "DiscoveryEngine",
]

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class DiscoveredSource:
    """Represents a discovered gaming library location or prefix path."""

    source_type: str  # 'steam_library', 'wine_prefix', 'filesystem_games', 'flatpak_launcher'
    path: Path
    label: str


@dataclass(slots=True)
class DiscoveryEngine:
    """Discovers installed gaming environments across filesystem, wine prefixes, and mounts."""

    def discover_all(self) -> list[DiscoveredSource]:
        """Perform comprehensive system discovery for gaming roots."""
        sources: list[DiscoveredSource] = []
        home = Path.home()

        # 1. Wine prefixes
        wine_dirs = [home / ".wine", home / ".local" / "share" / "wineprefixes"]
        for wdir in wine_dirs:
            if wdir.is_dir():
                if (wdir / "drive_c").is_dir():
                    sources.append(DiscoveredSource(source_type="wine_prefix", path=wdir, label=f"Wine Prefix ({wdir.name})"))
                else:
                    for child in wdir.iterdir():
                        if child.is_dir() and (child / "drive_c").is_dir():
                            sources.append(DiscoveredSource(source_type="wine_prefix", path=child, label=f"Wine Prefix ({child.name})"))

        # 2. Additional Steam libraries
        steam_root = home / ".local" / "share" / "Steam"
        vdf_path = steam_root / "steamapps" / "libraryfolders.vdf"
        if vdf_path.is_file():
            try:
                import vdf
                with vdf_path.open("r", encoding="utf-8", errors="ignore") as f:
                    data = vdf.load(f)

                folders = data.get("libraryfolders", {})
                for k, v in folders.items():
                    if isinstance(v, dict) and "path" in v:
                        lib_p = Path(v["path"]) / "steamapps"
                        if lib_p.is_dir():
                            sources.append(DiscoveredSource(source_type="steam_library", path=lib_p, label=f"Steam Library ({lib_p.parent.name})"))
            except Exception as err:
                logger.debug("DiscoveryEngine failed reading libraryfolders.vdf: %s", err)

        # 3. External drive mounts (/media, /mnt)
        for mroot in (Path("/media"), Path("/mnt")):
            if mroot.is_dir():
                try:
                    for mount in mroot.iterdir():
                        if mount.is_dir():
                            for gdir in ("Games", "games", "SteamLibrary"):
                                candidate = mount / gdir
                                if candidate.is_dir():
                                    sources.append(DiscoveredSource(source_type="filesystem_games", path=candidate, label=f"Game Folder ({candidate})"))
                except OSError:
                    pass

        return sources
