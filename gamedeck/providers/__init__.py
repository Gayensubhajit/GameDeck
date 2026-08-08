"""Game provider plugin base class and registry for GameDeck."""

from __future__ import annotations

from abc import ABC, abstractmethod

from gamedeck.models import Game

__all__ = ["BaseProvider", "Provider", "GameProvider"]


class BaseProvider(ABC):
    """Abstract base class for all GameDeck game library providers.

    Every built-in and third-party provider must subclass ``BaseProvider`` and
    implement the three abstract members below.  The ``ProviderManager`` auto-
    discovers concrete subclasses from the ``gamedeck.providers`` package at
    runtime — no manual registration is required.

    Class attributes:
        name: Unique lowercase identifier for this provider (e.g. ``"steam"``).
        priority: Integer precedence used during deduplication.  Higher value
            wins when the same game appears in multiple providers.
            Built-in scale: Steam 50, Heroic 40, Lutris 30, Native 20,
            Filesystem 10.

    Methods to implement:
        enabled(): Return ``True`` if this provider can run on the current
            system (e.g. the relevant launcher is installed).  Disabled
            providers are silently skipped by ``ProviderManager``.
        scan(): Perform the actual game discovery and return a list of
            :class:`~gamedeck.models.Game` instances.
    """

    #: Unique lowercase string identifier for this provider.
    name: str

    #: Integer deduplication precedence — higher value wins.
    priority: int

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def enabled(self) -> bool:
        """Return ``True`` if this provider is available on the current system.

        Providers should inspect the filesystem (e.g. launcher config dirs,
        installed binaries) to determine availability.  Returning ``False``
        causes the ``ProviderManager`` to skip this provider without error.

        Returns:
            ``True`` when the provider can be used, ``False`` otherwise.
        """

    @abstractmethod
    def scan(self) -> list[Game]:
        """Scan and return all discovered games for this provider.

        Returns:
            A list of :class:`~gamedeck.models.Game` instances.
        """

    # ------------------------------------------------------------------
    # Backwards-compatibility shim
    # ------------------------------------------------------------------

    def get_games(self) -> list[Game]:
        """Alias for :meth:`scan` retained for backwards compatibility.

        Existing code that calls ``provider.get_games()`` continues to work
        without modification.

        Returns:
            A list of :class:`~gamedeck.models.Game` instances.
        """
        return self.scan()


# ---------------------------------------------------------------------------
# Backwards-compatibility aliases
# ---------------------------------------------------------------------------

#: Alias for ``BaseProvider`` — kept so existing imports of ``Provider``
#: continue to resolve without change.
Provider = BaseProvider

#: Legacy alias used in early versions of the codebase.
GameProvider = BaseProvider
