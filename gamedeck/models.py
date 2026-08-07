"""Data models for GameDeck."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

__all__ = ["Game"]


@dataclass(slots=True)
class Game:
    """Core data model representing a game across various providers and launchers.

    Attributes:
        id: Unique identifier for the game.
        name: Display name / title of the game.
        source: Provider source identifier (e.g. steam, lutris, heroic, native, filesystem).
        launcher: Launcher backend identifier (e.g. steam, lutris, native, wine, proton, bottles).
        executable: Path to the executable or launch target, if applicable.
        icon: Path to the game icon file, if available.
        cover: Path to the game cover art image, if available.
        installed: Whether the game is currently installed.
        favorite: Whether the game has been marked as a favorite.
        appid: Provider-specific application identifier (e.g. Steam AppID or Lutris slug).
    """

    id: str
    name: str
    source: str
    launcher: str
    executable: Path | None = None
    icon: Path | None = None
    cover: Path | None = None
    installed: bool = True
    favorite: bool = False
    appid: str | None = None
