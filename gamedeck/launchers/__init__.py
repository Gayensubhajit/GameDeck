"""GameDeck launcher backends for executing games across platforms."""

from __future__ import annotations

import logging
import subprocess
from typing import Any, Protocol, runtime_checkable

from gamedeck.launchers.lutris import LutrisLauncher
from gamedeck.launchers.native import NativeLauncher
from gamedeck.launchers.steam import SteamLauncher
from gamedeck.launchers.wine import WineLauncher
from gamedeck.models import Game

__all__ = [
    "Launcher",
    "SteamLauncher",
    "LutrisLauncher",
    "NativeLauncher",
    "WineLauncher",
    "launch",
    "get_launcher",
]

logger = logging.getLogger(__name__)


@runtime_checkable
class Launcher(Protocol):
    """Protocol interface for game launcher backends."""

    def launch(
        self,
        game: Game,
        extra_args: list[str] | None = None,
        **kwargs: Any,
    ) -> subprocess.Popen[Any]:
        """Launch the specified game.

        Args:
            game: Game model instance to execute.
            extra_args: Optional additional command-line parameters.
            **kwargs: Backend-specific arguments.

        Returns:
            The spawned subprocess.Popen instance.
        """
        ...


def get_launcher(launcher_type: str) -> Launcher:
    """Resolve and return an instance of the appropriate launcher backend.

    Args:
        launcher_type: Launcher identifier (e.g. 'steam', 'lutris', 'native', 'wine', 'proton').

    Returns:
        An instance of the corresponding launcher backend.

    Raises:
        ValueError: If launcher_type is unrecognized.
    """
    key = launcher_type.lower().strip()
    if key in ("steam",):
        return SteamLauncher()
    if key in ("lutris",):
        return LutrisLauncher()
    if key in ("native", "linux"):
        return NativeLauncher()
    if key in ("wine", "proton", "bottles"):
        return WineLauncher()

    raise ValueError(f"Unsupported launcher backend: '{launcher_type}'")


def launch(game: Game, extra_args: list[str] | None = None, **kwargs: Any) -> subprocess.Popen[Any]:
    """Execute a game using its designated launcher backend.

    Dispatches execution to the corresponding launcher based on game.launcher
    (Steam, Lutris, Native, or Wine) without touching provider code.

    Args:
        game: Game model instance to execute.
        extra_args: Optional additional command-line parameters.
        **kwargs: Additional backend-specific keyword arguments (e.g. env, wine_prefix).

    Returns:
        The spawned subprocess.Popen instance.
    """
    logger.info("Executing game '%s' [%s] using launcher '%s'", game.name, game.id, game.launcher)
    launcher = get_launcher(game.launcher)
    return launcher.launch(game, extra_args=extra_args, **kwargs)
