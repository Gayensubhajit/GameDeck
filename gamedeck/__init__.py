"""GameDeck - Unified game launcher for Linux.

GameDeck aggregates Steam, Lutris, Heroic Games Launcher, Native Linux apps, and
custom Windows games into a single searchable Rofi dmenu interface. It provides
collections, tags, launch profiles, backup/restore, and background metadata caching
with zero latency startup (<10ms from SQLite cache).

Version: 0.5.0
"""

from __future__ import annotations

from gamedeck.api import GameDeckAPI
from gamedeck.app import GameDeck
from gamedeck.backup import BackupManager
from gamedeck.events import EventBus
from gamedeck.models import Game
from gamedeck.plugins import PluginRegistry
from gamedeck.profiles import ProfileManager
from gamedeck.saves import SaveManager
from gamedeck.scanner import Scanner
from gamedeck.screenshots import ScreenshotManager

__version__ = "0.6.0"
__all__ = [
    "__version__",
    "GameDeck",
    "GameDeckAPI",
    "Game",
    "Scanner",
    "BackupManager",
    "ProfileManager",
    "SaveManager",
    "ScreenshotManager",
    "EventBus",
    "PluginRegistry",
]
