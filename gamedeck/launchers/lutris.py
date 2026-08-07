"""Lutris game launcher backend for GameDeck."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any

from gamedeck.models import Game

__all__ = ["LutrisLauncher", "launch"]


@dataclass(slots=True)
class LutrisLauncher:
    """Launcher backend for executing games registered through Lutris.

    Attributes:
        lutris_bin: Name or absolute path of the Lutris binary executable.
    """

    lutris_bin: str = "lutris"

    def launch(self, game: Game, extra_args: list[str] | None = None) -> subprocess.Popen[Any]:
        """Launch a Lutris game via the Lutris protocol URI or command-line runner.

        Args:
            game: Game model instance to execute.
            extra_args: Optional additional command-line parameters to pass.

        Returns:
            The spawned subprocess.Popen instance.

        Raises:
            ValueError: If the game has no valid slug or identifier.
            RuntimeError: If the Lutris executable is not found in PATH.
        """
        slug = game.appid
        if not slug:
            slug = game.id.removeprefix("lutris_")

        if not slug:
            raise ValueError(f"Cannot launch Lutris game '{game.name}': Missing valid slug or appid.")

        executable = shutil.which(self.lutris_bin)
        if executable is None:
            # Fallback to xdg-open if lutris binary is not directly available
            xdg_open = shutil.which("xdg-open")
            if xdg_open is not None:
                cmd = [xdg_open, f"lutris:rungame/{slug}"]
                return subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
            raise RuntimeError(
                f"Lutris executable '{self.lutris_bin}' was not found in PATH."
            )

        cmd = [executable, f"lutris:rungame/{slug}"]
        if extra_args:
            cmd.extend(extra_args)

        return subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )


def launch(game: Game, extra_args: list[str] | None = None) -> subprocess.Popen[Any]:
    """Convenience function to launch a Lutris game.

    Args:
        game: Game model instance.
        extra_args: Optional extra arguments.

    Returns:
        The spawned subprocess.Popen instance.
    """
    launcher = LutrisLauncher()
    return launcher.launch(game, extra_args=extra_args)
