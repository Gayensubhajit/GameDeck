"""Wine game launcher backend for GameDeck."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gamedeck.launchers import BaseLauncher
from gamedeck.models import Game

__all__ = ["WineLauncher", "launch"]

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class WineLauncher(BaseLauncher):
    """Launcher backend for executing Windows games via Wine or Proton.

    Class attributes:
        name: Launcher identifier — ``"wine"``.
        aliases: Also responds to ``"proton"`` and ``"bottles"``.

    Attributes:
        wine_bin: Binary executable name or path for Wine (e.g. ``'wine'``, ``'wine64'``, ``'umu-run'``).
        default_prefix: Optional default WINEPREFIX path to use.
    """

    name: str = field(default="wine", init=False, repr=False, compare=False)
    aliases: tuple[str, ...] = field(
        default=("proton", "bottles"), init=False, repr=False, compare=False
    )

    wine_bin: str = "wine"
    default_prefix: Path | str | None = None

    def launch(
        self,
        game: Game,
        extra_args: list[str] | None = None,
        wine_prefix: Path | str | None = None,
        env: dict[str, str] | None = None,
    ) -> subprocess.Popen[Any]:
        """Launch a Windows executable using Wine.

        Args:
            game: Game model instance containing the target .exe path.
            extra_args: Optional command-line arguments to pass to the Windows executable.
            wine_prefix: Optional custom WINEPREFIX directory.
            env: Optional environment variables.

        Returns:
            The spawned subprocess.Popen instance.

        Raises:
            ValueError: If game.executable is missing or invalid.
            RuntimeError: If the Wine executable is not found in PATH.
        """
        if game.executable is None:
            raise ValueError(f"Cannot launch Wine game '{game.name}': Missing executable path.")

        exe_path = Path(game.executable)
        if not exe_path.exists():
            raise ValueError(
                f"Cannot launch Wine game '{game.name}': Executable '{exe_path}' does not exist."
            )

        executable = shutil.which(self.wine_bin)
        if executable is None:
            # Fallback to wine64 if wine is not in PATH
            executable = shutil.which("wine64")
            if executable is None:
                raise RuntimeError(
                    f"Wine binary '{self.wine_bin}' was not found in PATH. "
                    "Please install Wine or Proton to launch Windows games."
                )

        working_dir = exe_path if exe_path.is_dir() else exe_path.parent

        cmd: list[str] = [executable, str(exe_path)]
        if extra_args:
            cmd.extend(extra_args)

        proc_env = os.environ.copy()

        # Set WINEPREFIX if provided
        prefix = wine_prefix or self.default_prefix
        if prefix is not None:
            proc_env["WINEPREFIX"] = str(Path(prefix).resolve())

        if env:
            proc_env.update(env)

        logger.info("Spawning Wine process: %s (cwd=%s)", cmd, working_dir)
        return subprocess.Popen(
            cmd,
            cwd=str(working_dir),
            env=proc_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )


def launch(
    game: Game,
    extra_args: list[str] | None = None,
    wine_bin: str = "wine",
    wine_prefix: Path | str | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.Popen[Any]:
    """Convenience function to launch a Windows game using Wine.

    Args:
        game: Game model instance.
        extra_args: Optional extra arguments.
        wine_bin: Wine executable name.
        wine_prefix: Optional WINEPREFIX path.
        env: Optional environment variables.

    Returns:
        The spawned subprocess.Popen instance.
    """
    launcher = WineLauncher(wine_bin=wine_bin, default_prefix=wine_prefix)
    return launcher.launch(game, extra_args=extra_args, env=env)
