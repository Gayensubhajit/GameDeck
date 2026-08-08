"""Core data models for GameDeck.

This module defines the central ``Game`` dataclass that flows through every layer
of the application — from provider scanning to launcher backends to the Rofi UI.
All other modules depend on this module; it must not import from any other
gamedeck submodule to avoid circular imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

__all__ = ["Game"]


@dataclass(slots=True)
class Game:
    """Core data model representing a discovered game across all providers and launchers.

    ``Game`` instances are immutable by convention — fields are only mutated in
    ``app.py`` when the user explicitly edits properties via the context menu.
    All provider modules produce new ``Game`` instances; they never mutate shared state.

    Attributes:
        id: Globally unique identifier for the game, scoped by provider
            (e.g. ``"steam_730"``, ``"lutris_black-myth-wukong-1234"``).
        name: Human-readable display title (e.g. ``"Counter-Strike 2"``).
        source: Provider that discovered this game. One of:
            ``"steam"``, ``"lutris"``, ``"heroic"``, ``"native"``, ``"filesystem"``.
        launcher: Backend used to launch the game. One of:
            ``"steam"``, ``"lutris"``, ``"heroic"``, ``"native"``, ``"wine"``,
            ``"proton"``, ``"bottles"``.
        executable: Resolved path to the launch target binary or script, if applicable.
            May be ``None`` for protocol-based launchers (Steam, Lutris slug).
        icon: Path to a resolved icon image file (PNG, SVG, or XPM), if available.
        logo: Path to a title logo / wordmark image, if available.
        hero: Path to a wide hero/banner image (typically 16:9), if available.
        cover: Path to a portrait cover art image (typically 2:3), if available.
        installed: Whether the game is currently detected as installed.
            Defaults to ``True`` because uninstalled games are generally not shown.
        favorite: Whether the user has starred this game as a favorite.
            Favorites are sorted to the top of all library views.
        appid: Provider-specific application identifier used to build launch URLs
            (e.g. ``"730"`` for Steam, ``"black-myth-wukong"`` for Lutris slug).
        last_played: ISO 8601 UTC timestamp of the most recent launch recorded
            by GameDeck (e.g. ``"2026-01-15T14:32:00+00:00"``), or ``None`` if
            the game has never been launched through GameDeck.
        launch_count: Total number of launches recorded by GameDeck for this game.
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
    date_added: str | None = None
    version: str | None = None
    notes: str | None = None
    hidden: bool = False
    platform: str | None = None
    wine_version: str | None = None
    playtime_minutes: int = 0

    def __str__(self) -> str:
        """Return a concise human-readable string for logging and debugging."""
        fav_tag = " ★" if self.favorite else ""
        return f"<Game {self.id!r} name={self.name!r} source={self.source}{fav_tag}>"
