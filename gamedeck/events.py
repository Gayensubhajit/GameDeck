"""Event Bus system for GameDeck providing thread-safe pub/sub event dispatching."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Type

__all__ = [
    "Event",
    "GameAdded",
    "GameRemoved",
    "ArtworkDownloaded",
    "MetadataUpdated",
    "CollectionChanged",
    "FavoriteChanged",
    "SearchIndexed",
    "EventBus",
    "get_event_bus",
]

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Event:
    """Base class for all GameDeck domain events."""

    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass(slots=True)
class GameAdded(Event):
    """Fired when a new game is discovered or added to the library."""

    game_id: str = ""
    game_title: str = ""
    source: str = ""


@dataclass(slots=True)
class GameRemoved(Event):
    """Fired when a game is removed from the library."""

    game_id: str = ""
    game_title: str = ""


@dataclass(slots=True)
class ArtworkDownloaded(Event):
    """Fired when artwork asset download completes."""

    game_id: str = ""
    art_type: str = ""
    file_path: str = ""


@dataclass(slots=True)
class MetadataUpdated(Event):
    """Fired when game properties or metadata attributes are updated."""

    game_id: str = ""
    updated_fields: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CollectionChanged(Event):
    """Fired when a collection is created, modified, or deleted."""

    collection_id: str = ""
    action: str = ""  # 'created', 'updated', 'deleted', 'game_added', 'game_removed'
    game_id: str | None = None


@dataclass(slots=True)
class FavoriteChanged(Event):
    """Fired when a game's favorite status is toggled."""

    game_id: str = ""
    favorite: bool = False


@dataclass(slots=True)
class SearchIndexed(Event):
    """Fired when the in-memory SearchIndex is rebuilt."""

    game_count: int = 0
    token_count: int = 0


EventHandler = Callable[[Any], None]


class EventBus:
    """Thread-safe publish/subscribe EventBus dispatcher."""

    _instance: EventBus | None = None

    def __init__(self) -> None:
        self._subscribers: dict[Type[Event], list[EventHandler]] = {}

    @classmethod
    def get_instance(cls) -> EventBus:
        """Return global singleton EventBus instance."""
        if cls._instance is None:
            cls._instance = EventBus()
        return cls._instance

    def subscribe(self, event_type: Type[Event], handler: EventHandler) -> None:
        """Subscribe a handler callback to a specific event type."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        if handler not in self._subscribers[event_type]:
            self._subscribers[event_type].append(handler)
            logger.debug("Subscribed %s to %s", handler.__name__, event_type.__name__)

    def unsubscribe(self, event_type: Type[Event], handler: EventHandler) -> None:
        """Unsubscribe a handler callback from an event type."""
        if event_type in self._subscribers and handler in self._subscribers[event_type]:
            self._subscribers[event_type].remove(handler)

    def publish(self, event: Event) -> None:
        """Broadcast an event instance to all registered subscriber callbacks."""
        event_type = type(event)
        handlers = self._subscribers.get(event_type, [])
        logger.debug("Publishing event %s to %d subscribers", event_type.__name__, len(handlers))
        for handler in handlers:
            try:
                handler(event)
            except Exception as err:
                logger.error("Error handling event %s in handler %s: %s", event_type.__name__, handler, err)


def get_event_bus() -> EventBus:
    """Convenience function to get the shared EventBus instance."""
    return EventBus.get_instance()
