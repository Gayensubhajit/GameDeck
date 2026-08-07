"""Game provider implementations for GameDeck."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from gamedeck.models import Game

__all__ = ["Provider", "GameProvider"]


@runtime_checkable
class Provider(Protocol):
    """Protocol interface for game library providers."""

    def get_games(self) -> list[Game]:
        """Scan and return discovered Game model instances.

        Returns:
            A list of Game model instances.
        """
        ...


# Backwards compatibility alias
GameProvider = Provider
