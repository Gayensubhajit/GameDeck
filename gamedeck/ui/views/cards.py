"""Extensible Card Layout models for GameDeck Grid View.

Provides future-ready card styling configurations:
- PortraitCardStyle (2:3 aspect ratio, steam cover style)
- CompactCardStyle (1:1 compact square grid)
- LandscapeCardStyle (16:9 banner/capsule style)
- HeroCardStyle (Cinematic hero style)
- CarouselStyle (Horizontal spotlight style)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from gamedeck.models import Game


@dataclass(slots=True)
class CardStyle:
    """Base layout properties and formatting for game cards."""

    name: str = "base"
    aspect_ratio: str = "2:3"
    icon_size_px: int = 180
    show_badge: bool = True
    show_favorite: bool = True
    orientation: str = "vertical"
    preferred_artwork: str = "portrait"

    def format_card_label(self, game: Game) -> str:
        """Format the card label with title, favorite star, and launcher badge."""
        title = (game.name or "Unknown Game").strip()
        fav_star = "★ " if game.favorite else ""

        badge = ""
        if self.show_badge:
            launcher_name = (game.launcher or game.source or "native").capitalize()
            badge = f" [{launcher_name}]"

        return f"{fav_star}{title}{badge}"


@dataclass(slots=True)
class PortraitCardStyle(CardStyle):
    """Standard vertical poster / cover card style (2:3 aspect ratio)."""

    name: str = "portrait"
    aspect_ratio: str = "2:3"
    icon_size_px: int = 200
    preferred_artwork: str = "portrait"


@dataclass(slots=True)
class CompactCardStyle(CardStyle):
    """Dense compact square card style for high information density."""

    name: str = "compact"
    aspect_ratio: str = "1:1"
    icon_size_px: int = 120
    preferred_artwork: str = "icon"


@dataclass(slots=True)
class LandscapeCardStyle(CardStyle):
    """Horizontal capsule / banner card style (16:9 aspect ratio)."""

    name: str = "landscape"
    aspect_ratio: str = "16:9"
    icon_size_px: int = 160
    preferred_artwork: str = "capsule"


@dataclass(slots=True)
class HeroCardStyle(CardStyle):
    """Large cinematic hero card style."""

    name: str = "hero"
    aspect_ratio: str = "21:9"
    icon_size_px: int = 260
    preferred_artwork: str = "hero"


@dataclass(slots=True)
class CarouselStyle(CardStyle):
    """Recently played horizontal carousel card style."""

    name: str = "carousel"
    aspect_ratio: str = "16:9"
    icon_size_px: int = 180
    orientation: str = "horizontal"
    preferred_artwork: str = "hero"


CARD_STYLES: dict[str, CardStyle] = {
    "portrait": PortraitCardStyle(),
    "compact": CompactCardStyle(),
    "landscape": LandscapeCardStyle(),
    "hero": HeroCardStyle(),
    "carousel": CarouselStyle(),
}


def get_card_style(name: str | None = None) -> CardStyle:
    """Retrieve card style by name or default to PortraitCardStyle."""
    if not name:
        return CARD_STYLES["portrait"]
    return CARD_STYLES.get(name.lower().strip(), CARD_STYLES["portrait"])
