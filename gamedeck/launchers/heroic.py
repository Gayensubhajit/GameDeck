"""Heroic Games Launcher backend for GameDeck."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any

from gamedeck.launchers import BaseLauncher
from gamedeck.models import Game

__all__ = ["HeroicLauncher", "launch"]

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class HeroicLauncher(BaseLauncher):
    """Launcher backend for executing games registered through Heroic Games Launcher.

    Class attributes:
        name: Launcher identifier — ``"heroic"``.
        aliases: No additional aliases.

    Attributes:
        heroic_bin: Name or absolute path of the Heroic binary executable.
        flatpak_app_id: Flatpak Application ID for Flatpak installations of Heroic.
    """

    name: str = field(default="heroic", init=False, repr=False, compare=False)
    aliases: tuple[str, ...] = field(default=(), init=False, repr=False, compare=False)

    heroic_bin: str = "heroic"
    flatpak_app_id: str = "com.heroicgameslauncher.hgl"

    def launch(self, game: Game, extra_args: list[str] | None = None) -> subprocess.Popen[Any]:
        """Launch a Heroic game via CLI runner or Heroic protocol URI.

        Args:
            game: Game model instance to execute.
            extra_args: Optional additional command-line parameters to pass.

        Returns:
            The spawned subprocess.Popen instance.

        Raises:
            ValueError: If the game has no valid appid or identifier.
            RuntimeError: If Heroic is not found in PATH, Flatpak, or via xdg-open.
        """
        app_name = game.appid
        if not app_name:
            app_name = game.id.removeprefix("heroic_")

        if not app_name:
            raise ValueError(f"Cannot launch Heroic game '{game.name}': Missing valid appid.")

        uri = f"heroic://launch/{app_name}"

        # 1. Native Heroic binary executable
        executable = shutil.which(self.heroic_bin)
        if executable is not None:
            cmd = [executable, "--no-gui", uri]
            if extra_args:
                cmd.extend(extra_args)

            logger.info("Spawning Heroic process: %s", cmd)
            return subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )

        # 2. Flatpak Heroic installation
        flatpak = shutil.which("flatpak")
        if flatpak is not None:
            cmd = [flatpak, "run", self.flatpak_app_id, "--no-gui", uri]
            if extra_args:
                cmd.extend(extra_args)

            logger.info("Spawning Flatpak Heroic process: %s", cmd)
            return subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )

        # 3. Fallback to xdg-open protocol handler
        xdg_open = shutil.which("xdg-open")
        if xdg_open is not None:
            cmd = [xdg_open, uri]
            logger.info("Spawning Heroic URI via xdg-open: %s", cmd)
            return subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )

        raise RuntimeError(
            f"Heroic Games Launcher was not found. Please install Heroic via your package manager or Flatpak."
        )


def launch(game: Game, extra_args: list[str] | None = None) -> subprocess.Popen[Any]:
    """Convenience function to launch a Heroic game.

    Args:
        game: Game model instance.
        extra_args: Optional extra arguments.

    Returns:
        The spawned subprocess.Popen instance.
    """
    launcher = HeroicLauncher()
    return launcher.launch(game, extra_args=extra_args)
