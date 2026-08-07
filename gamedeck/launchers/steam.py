"""Steam game launcher backend for GameDeck."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any

from gamedeck.models import Game

__all__ = ["SteamLauncher", "launch"]


@dataclass(slots=True)
class SteamLauncher:
    """Launcher backend for executing games registered through Steam.

    Attributes:
        steam_bin: Name or absolute path of the Steam binary executable.
    """

    steam_bin: str = "steam"

    def launch(self, game: Game, extra_args: list[str] | None = None) -> subprocess.Popen[Any]:
        """Launch a Steam game via Steam URI or command-line parameters.

        Args:
            game: Game model instance to execute.
            extra_args: Optional additional command-line parameters to pass.

        Returns:
            The spawned subprocess.Popen instance.

        Raises:
            ValueError: If the game has no valid appid or identifier.
            RuntimeError: If the Steam executable is not found in PATH.
        """
        appid = game.appid
        if not appid:
            # Fallback to id parsing if appid is not set
            appid = game.id.removeprefix("steam_")

        if not appid:
            raise ValueError(f"Cannot launch Steam game '{game.name}': Missing valid appid.")

        executable = shutil.which(self.steam_bin)
        if executable is None:
            # Fallback to xdg-open if steam binary is not directly available
            xdg_open = shutil.which("xdg-open")
            if xdg_open is not None:
                cmd = [xdg_open, f"steam://rungameid/{appid}"]
                return subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
            raise RuntimeError(
                f"Steam executable '{self.steam_bin}' was not found in PATH."
            )

        # Standard launch command via Steam URI
        cmd = [executable, f"steam://rungameid/{appid}"]
        if extra_args:
            cmd.extend(extra_args)

        return subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )


def launch(game: Game, extra_args: list[str] | None = None) -> subprocess.Popen[Any]:
    """Convenience function to launch a Steam game.

    Args:
        game: Game model instance.
        extra_args: Optional extra arguments.

    Returns:
        The spawned subprocess.Popen instance.
    """
    launcher = SteamLauncher()
    return launcher.launch(game, extra_args=extra_args)
