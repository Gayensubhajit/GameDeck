"""Native Linux game launcher backend for GameDeck."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gamedeck.models import Game

__all__ = ["NativeLauncher", "launch"]


@dataclass(slots=True)
class NativeLauncher:
    """Launcher backend for executing native Linux game binaries and scripts."""

    def launch(
        self,
        game: Game,
        extra_args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> subprocess.Popen[Any]:
        """Launch a native Linux game binary.

        Args:
            game: Game model instance containing the target executable path.
            extra_args: Optional additional command-line parameters to pass to the executable.
            env: Optional environment variables to merge with the current process environment.

        Returns:
            The spawned subprocess.Popen instance.

        Raises:
            ValueError: If game.executable is None or points to a non-existent path.
        """
        if game.executable is None:
            raise ValueError(f"Cannot launch native game '{game.name}': Missing executable path.")

        exe_path = Path(game.executable)
        if not exe_path.exists():
            raise ValueError(
                f"Cannot launch native game '{game.name}': Executable '{exe_path}' does not exist."
            )

        # Set working directory to the parent directory containing the binary
        working_dir = exe_path if exe_path.is_dir() else exe_path.parent

        cmd: list[str] = [str(exe_path)]
        if extra_args:
            cmd.extend(extra_args)

        # Merge environment variables if provided
        proc_env = os.environ.copy()
        if env:
            proc_env.update(env)

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
    env: dict[str, str] | None = None,
) -> subprocess.Popen[Any]:
    """Convenience function to launch a native Linux game.

    Args:
        game: Game model instance.
        extra_args: Optional extra command line arguments.
        env: Optional environment variables.

    Returns:
        The spawned subprocess.Popen instance.
    """
    launcher = NativeLauncher()
    return launcher.launch(game, extra_args=extra_args, env=env)
