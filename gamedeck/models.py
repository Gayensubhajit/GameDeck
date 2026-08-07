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
        logo: Path to the game logo / title image, if available.
        hero: Path to the game wide hero / banner image, if available.
        cover: Path to the game portrait cover art image, if available.
        installed: Whether the game is currently installed.
        favorite: Whether the game has been marked as a favorite.
        appid: Provider-specific application identifier (e.g. Steam AppID or Lutris slug).
        last_played: ISO timestamp string of the last launch time, if recorded.
        launch_count: Total number of times launched through GameDeck.
    """

    id: str
    name: str
    source: str
    launcher: str
    executable: Path | None = None
    icon: Path | None = None
    logo: Path | None = None
    hero: Path | None = None
    cover: Path | None = None
    installed: bool = True
    favorite: bool = False
    appid: str | None = None
    last_played: str | None = None
    launch_count: int = 0
