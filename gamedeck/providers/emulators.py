"""Emulator library provider plugin for RetroArch, RPCS3, and PCSX2."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from gamedeck.models import Game
from gamedeck.plugins import BaseProviderPlugin

__all__ = ["EmulatorProvider"]

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class EmulatorProvider(BaseProviderPlugin):
    """Discovers emulated games across RetroArch, RPCS3, and PCSX2."""

    name: str = "emulators"
    display_name: str = "Emulators (RetroArch / RPCS3 / PCSX2)"

    def is_available(self) -> bool:
        """Check if any emulator config directory exists."""
        home = Path.home()
        paths = [
            home / ".config" / "retroarch" / "playlists",
            home / ".config" / "rpcs3" / "dev_hdd0" / "game",
            home / ".config" / "PCSX2" / "inis",
        ]
        return any(p.exists() for p in paths)

    def scan(self) -> list[Game]:
        """Scan and return discovered emulator games."""
        games: list[Game] = []
        home = Path.home()

        # 1. RetroArch Playlists
        retroarch_playlists = home / ".config" / "retroarch" / "playlists"
        if retroarch_playlists.is_dir():
            for lfile in retroarch_playlists.glob("*.lpl"):
                try:
                    import json
                    with lfile.open("r", encoding="utf-8") as f:
                        data = json.load(f)

                    items = data.get("items", []) if isinstance(data, dict) else []
                    for item in items:
                        label = item.get("label", "")
                        path_str = item.get("path", "")
                        core_path = item.get("core_path", "")
                        if label:
                            clean_name = label.split("(")[0].strip()
                            gid = f"retroarch_{lfile.stem.lower()}_{clean_name.lower().replace(' ', '_')}"
                            games.append(
                                Game(
                                    id=gid,
                                    name=f"[RetroArch] {clean_name}",
                                    source="retroarch",
                                    launcher="retroarch",
                                    executable=Path(path_str) if path_str else None,
                                    installed=True,
                                )
                            )
                except Exception as err:
                    logger.debug("EmulatorProvider failed reading RetroArch playlist '%s': %s", lfile, err)

        # 2. RPCS3 Installed PS3 Games
        rpcs3_games = home / ".config" / "rpcs3" / "dev_hdd0" / "game"
        if rpcs3_games.is_dir():
            for child in rpcs3_games.iterdir():
                sfo = child / "PARAM.SFO"
                if sfo.is_file():
                    gid = f"rpcs3_{child.name.lower()}"
                    games.append(
                        Game(
                            id=gid,
                            name=f"[RPCS3] {child.name}",
                            source="rpcs3",
                            launcher="rpcs3",
                            executable=child,
                            installed=True,
                        )
                    )

        return games
