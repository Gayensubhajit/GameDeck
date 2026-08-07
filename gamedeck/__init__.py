"""GameDeck - Unified game launcher for Linux."""

from gamedeck.app import GameDeck
from gamedeck.models import Game
from gamedeck.scanner import Scanner

__all__ = ["GameDeck", "Game", "Scanner"]
