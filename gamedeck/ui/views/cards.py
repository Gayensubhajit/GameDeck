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
    show_playtime: bool = False
    show_installed: bool = True
    orientation: str = "vertical"
    preferred_artwork: str = "portrait"

    # Launcher badge color hints (used by themes; not rendered directly in label)
    LAUNCHER_COLORS: ClassVar[dict[str, str]] = {
        "steam": "#1b6fa8",
        "lutris": "#f97316",
        "heroic": "#d4a12a",
        "native": "#00e699",
        "wine": "#dc2626",
        "proton": "#dc2626",
        "bottles": "#9333ea",
        "filesystem": "#64748b",
    }

    def format_card_label(self, game: Game, *, playtime_minutes: int = 0) -> str:
        """Format the card label with title, favorite star, launcher badge, playtime, and installed indicator."""
        title = (game.name or "Unknown Game").strip()
        fav_star = "★ " if (self.show_favorite and game.favorite) else ""

        badge = ""
        if self.show_badge:
            raw_launcher = (game.launcher or game.source or "native").upper().strip()
            badge_map = {
                "FILESYSTEM": "WINE" if getattr(game, "wine_version", None) else "NATIVE",
                "COM.USEBOTTLES.BOTTLES": "BOTTLES",
                "GOG-GALAXY": "GOG",
                "RETROARCH": "RETROARCH",
                "RPCS3": "RPCS3",
                "PCSX2": "PCSX2",
                "MOONLIGHT": "MOONLIGHT",
                "SUNSHINE": "SUNSHINE",
            }
            badge_text = badge_map.get(raw_launcher, raw_launcher)
            badge = f"  [{badge_text}]"

        # Installed dot indicator (• if installed, □ if not)
        installed_dot = ""
        if self.show_installed:
            installed_dot = " •" if game.installed else " □"

        # Compact playtime suffix (only when > 0 and enabled)
        playtime_sfx = ""
        if self.show_playtime:
            total_mins = playtime_minutes or getattr(game, "playtime_minutes", 0)
            if total_mins > 0:
                hours = total_mins // 60
                mins = total_mins % 60
                playtime_sfx = f"  ⏱ {hours}h" if hours > 0 else f"  ⏱ {mins}m"

        return f"{fav_star}{title}{badge}{installed_dot}{playtime_sfx}"


@dataclass(slots=True)
class PortraitCardStyle(CardStyle):
    """Standard vertical poster / cover card style (2:3 aspect ratio)."""

    name: str = "portrait"
    aspect_ratio: str = "2:3"
    icon_size_px: int = 140
    show_playtime: bool = True
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


@dataclass(slots=True)
class DeckCardStyle(CardStyle):
    """Console Deck style card matching gamepad console aesthetics with big cover art."""

    name: str = "deck"
    aspect_ratio: str = "1:1"
    icon_size_px: int = 190
    show_badge: bool = False
    show_favorite: bool = False
    show_installed: bool = False
    preferred_artwork: str = "portrait"


CARD_STYLES: dict[str, CardStyle] = {
    "portrait": PortraitCardStyle(),
    "deck": DeckCardStyle(),
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
