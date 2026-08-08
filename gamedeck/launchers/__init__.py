"""GameDeck launcher backends for executing games across platforms."""

from __future__ import annotations

import importlib
import logging
import pkgutil
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from gamedeck.models import Game

__all__ = [
    "BaseLauncher",
    "Launcher",
    "LauncherManager",
    "SteamLauncher",
    "HeroicLauncher",
    "LutrisLauncher",
    "NativeLauncher",
    "WineLauncher",
    "launch",
    "get_launcher",
]

logger = logging.getLogger(__name__)


class BaseLauncher(ABC):
    """Abstract base class for all GameDeck game launcher backends.

    Every built-in and third-party launcher must subclass ``BaseLauncher`` and
    implement the abstract members below.  ``LauncherManager`` auto-discovers
    concrete subclasses from the ``gamedeck.launchers`` package at runtime —
    no manual registration is required.

    Class attributes:
        name: Unique lowercase identifier for this launcher (e.g. ``"steam"``).
        aliases: Additional lowercase names that resolve to this launcher.
            For example ``WineLauncher`` declares ``aliases = ("proton", "bottles")``
            so games with ``launcher="proton"`` are dispatched here automatically.

    Methods to implement:
        launch(): Execute the game and return the spawned ``subprocess.Popen``.

    Providers must never be imported here.
    Launchers must never scan for games.
    """

    #: Unique lowercase string identifier for this launcher.
    name: str

    #: Additional name strings that also resolve to this launcher.
    aliases: tuple[str, ...]

    @abstractmethod
    def launch(
        self,
        game: Game,
        extra_args: list[str] | None = None,
        **kwargs: Any,
    ) -> subprocess.Popen[Any]:
        """Execute the given game and return the spawned process.

        Args:
            game: Game model instance to execute.
            extra_args: Optional additional command-line parameters.
            **kwargs: Backend-specific keyword arguments (e.g. ``env``, ``wine_prefix``).

        Returns:
            The spawned :class:`subprocess.Popen` instance.

        Raises:
            ValueError: If required game metadata is missing.
            RuntimeError: If the required system binary is not found.
        """


# ---------------------------------------------------------------------------
# Backwards-compatibility alias
# ---------------------------------------------------------------------------

#: Alias for ``BaseLauncher`` — kept so existing imports of ``Launcher``
#: continue to resolve without change.
Launcher = BaseLauncher


# ---------------------------------------------------------------------------
# Auto-discovery
# ---------------------------------------------------------------------------


def _discover_launcher_classes() -> dict[str, type[BaseLauncher]]:
    """Walk the ``gamedeck.launchers`` package and collect all concrete BaseLauncher subclasses.

    Each submodule is imported; any class that is a strict, non-abstract subclass
    of ``BaseLauncher`` with a ``name`` attribute is registered under both its
    primary ``name`` and every entry in its ``aliases`` tuple.

    Duplicate names are resolved in favour of the first discovery (alphabetical
    module order), so built-in launchers always take precedence over any
    accidentally clashing third-party module in the package.

    Returns:
        A flat mapping of ``{launcher_key: launcher_class}`` covering primary
        names and all declared aliases.
    """
    import gamedeck.launchers as _launchers_pkg  # local to avoid circular at module load

    registry: dict[str, type[BaseLauncher]] = {}

    pkg_path = _launchers_pkg.__path__  # type: ignore[attr-defined]
    pkg_name = _launchers_pkg.__name__

    for module_info in pkgutil.iter_modules(pkg_path):
        module_name = f"{pkg_name}.{module_info.name}"
        try:
            module = importlib.import_module(module_name)
        except Exception as err:  # pragma: no cover
            logger.warning("Failed to import launcher module '%s': %s", module_name, err)
            continue

        for attr_name in dir(module):
            obj = getattr(module, attr_name)
            if (
                isinstance(obj, type)
                and issubclass(obj, BaseLauncher)
                and obj is not BaseLauncher
                and not getattr(obj, "__abstractmethods__", None)
                and hasattr(obj, "name")
            ):
                # Read primary name from the dataclass field default
                try:
                    launcher_name: str = obj.__dataclass_fields__["name"].default  # type: ignore[attr-defined]
                except (AttributeError, KeyError):
                    launcher_name = getattr(obj, "name", "")

                if not launcher_name:
                    continue

                if launcher_name not in registry:
                    registry[launcher_name] = obj
                    logger.debug(
                        "Discovered launcher '%s' from %s", launcher_name, module_name
                    )

                # Expand aliases into the flat registry
                try:
                    aliases: tuple[str, ...] = obj.__dataclass_fields__["aliases"].default  # type: ignore[attr-defined]
                except (AttributeError, KeyError):
                    aliases = getattr(obj, "aliases", ())

                for alias in aliases:
                    if alias and alias not in registry:
                        registry[alias] = obj
                        logger.debug(
                            "Registered alias '%s' → %s from %s",
                            alias,
                            launcher_name,
                            module_name,
                        )

    return registry


# ---------------------------------------------------------------------------
# LauncherManager
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class LauncherManager:
    """Manager for resolving and dispatching game execution to the correct launcher backend.

    Automatically discovers concrete :class:`BaseLauncher` subclasses from the
    ``gamedeck.launchers`` package at runtime.  Adding a new launcher module to
    the package is sufficient for it to be picked up — no manual registration
    is needed.

    The manager maintains no persistent state; launcher classes are discovered
    on each call to :meth:`get_launcher`.  This keeps the design stateless and
    avoids global mutable state.
    """

    def get_launcher(self, launcher_type: str) -> BaseLauncher:
        """Resolve and return an instance of the appropriate launcher backend.

        Args:
            launcher_type: Launcher identifier string (e.g. ``"steam"``, ``"heroic"``,
                ``"lutris"``, ``"native"``, ``"wine"``, ``"proton"``, ``"bottles"``).

        Returns:
            An instantiated concrete :class:`BaseLauncher` for the requested type.

        Raises:
            ValueError: If ``launcher_type`` is not recognised by any discovered launcher.
        """
        key = launcher_type.lower().strip()
        registry = _discover_launcher_classes()
        cls = registry.get(key)
        if cls is None:
            raise ValueError(f"Unsupported launcher backend: '{launcher_type}'")
        return cls()

    def launch(
        self,
        game: Game,
        extra_args: list[str] | None = None,
        **kwargs: Any,
    ) -> subprocess.Popen[Any]:
        """Execute a game using its designated launcher backend.

        Dispatches execution to the corresponding launcher based on
        ``game.launcher`` (e.g. ``"steam"``, ``"heroic"``, ``"lutris"``,
        ``"native"``, ``"wine"``, ``"proton"``, ``"bottles"``).

        Providers must never be invoked here.
        Launchers must never scan games.

        Args:
            game: Game model instance to execute.
            extra_args: Optional additional command-line parameters.
            **kwargs: Backend-specific keyword arguments passed through to the launcher.

        Returns:
            The spawned :class:`subprocess.Popen` instance.
        """
        logger.info(
            "Executing game '%s' [%s] using launcher '%s'",
            game.name,
            game.id,
            game.launcher,
        )
        launcher = self.get_launcher(game.launcher)
        return launcher.launch(game, extra_args=extra_args, **kwargs)


# ---------------------------------------------------------------------------
# Module-level shims — preserved for backwards compatibility
# ---------------------------------------------------------------------------


def get_launcher(launcher_type: str) -> BaseLauncher:
    """Resolve and return an instance of the appropriate launcher backend.

    This is a thin shim over :class:`LauncherManager` preserved so that all
    existing call sites continue to work without modification.

    Args:
        launcher_type: Launcher identifier (e.g. ``'steam'``, ``'heroic'``,
            ``'lutris'``, ``'native'``, ``'wine'``, ``'proton'``).

    Returns:
        An instance of the corresponding launcher backend.

    Raises:
        ValueError: If ``launcher_type`` is unrecognized.
    """
    return LauncherManager().get_launcher(launcher_type)


def launch(
    game: Game,
    extra_args: list[str] | None = None,
    **kwargs: Any,
) -> subprocess.Popen[Any]:
    """Execute a game using its designated launcher backend.

    Dispatches execution to the corresponding launcher based on ``game.launcher``
    without touching provider code.

    Args:
        game: Game model instance to execute.
        extra_args: Optional additional command-line parameters.
        **kwargs: Additional backend-specific keyword arguments (e.g. ``env``, ``wine_prefix``).

    Returns:
        The spawned :class:`subprocess.Popen` instance.
    """
    return LauncherManager().launch(game, extra_args=extra_args, **kwargs)


# ---------------------------------------------------------------------------
# Deferred concrete imports — kept in __all__ for convenience; not used
# internally (discovery is done lazily via pkgutil/importlib).
# ---------------------------------------------------------------------------

from gamedeck.launchers.heroic import HeroicLauncher  # noqa: E402
from gamedeck.launchers.lutris import LutrisLauncher  # noqa: E402
from gamedeck.launchers.native import NativeLauncher  # noqa: E402
from gamedeck.launchers.steam import SteamLauncher  # noqa: E402
from gamedeck.launchers.wine import WineLauncher  # noqa: E402
