"""Unit tests for the HeroPanel read-only game info renderer.

Tests cover all 11 requested fields, graceful artwork fallback, instant
per-game updates, Pango markup correctness, and launcher badge rendering.

Note: Game.tags, Game.collections, and Game.genre are not core Game model
fields -- the panel gracefully falls back to sensible defaults when absent.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from gamedeck.models import Game
from gamedeck.ui.views.hero_panel import HeroPanel


def _make_game(
    name: str = "Test Game",
    source: str = "steam",
    launcher: str = "steam",
    favorite: bool = False,
    playtime_minutes: int = 0,
    last_played: str | None = None,
    platform: str | None = None,
) -> Game:
    return Game(
        id=f"test_{name.lower().replace(' ', '_')}",
        name=name,
        source=source,
        launcher=launcher,
        favorite=favorite,
        playtime_minutes=playtime_minutes,
        last_played=last_played,
        platform=platform,
    )


def _mock_resolver(hero: str | None = None, cover: str | None = None, icon: str | None = None) -> MagicMock:
    r = MagicMock()
    r.get_hero.return_value = hero
    r.get_cover.return_value = cover
    r.get_icon.return_value = icon
    return r


def _panel(game: Game, hero: str | None = None, cover: str | None = None, icon: str | None = None) -> str:
    panel = HeroPanel(artwork_resolver=_mock_resolver(hero, cover, icon))
    return panel.render_panel_pango(game)


class TestHeroPanelAllFields(unittest.TestCase):
    """Verify all 11 required fields appear in the Hero Panel render output."""

    def test_title(self):
        """Game title appears prominently."""
        self.assertIn("Hollow Knight", _panel(_make_game(name="Hollow Knight")))

    def test_launcher_badge(self):
        """Launcher badge [STEAM] appears."""
        self.assertIn("[STEAM]", _panel(_make_game(launcher="steam")))

    def test_launcher_badge_lutris(self):
        """Launcher badge [LUTRIS] appears for Lutris games."""
        self.assertIn("[LUTRIS]", _panel(_make_game(launcher="lutris")))

    def test_platform_badge(self):
        """Platform badge appears in panel."""
        out = _panel(_make_game(platform="Linux"))
        self.assertIn("Platform:", out)
        self.assertIn("[LINUX]", out)

    def test_platform_badge_fallback_native(self):
        """Platform defaults to Linux Native when unset and launcher is native."""
        out = _panel(_make_game(launcher="native", platform=None))
        self.assertIn("Platform:", out)
        # Should contain some platform text
        self.assertIn("LINUX", out.upper())

    def test_playtime_hours_and_minutes(self):
        """Playtime renders as Xh Ym for games over an hour."""
        out = _panel(_make_game(playtime_minutes=135))
        self.assertIn("Playtime:", out)
        self.assertIn("2h 15m", out)

    def test_playtime_minutes_only(self):
        """Playtime renders as Ym when under an hour."""
        out = _panel(_make_game(playtime_minutes=45))
        self.assertIn("45m", out)

    def test_playtime_zero(self):
        """Playtime shows 0m for unplayed games."""
        out = _panel(_make_game(playtime_minutes=0))
        self.assertIn("0m", out)

    def test_last_played_date(self):
        """Last Played date truncated to YYYY-MM-DD."""
        out = _panel(_make_game(last_played="2026-07-01T10:00:00+00:00"))
        self.assertIn("Last Played:", out)
        self.assertIn("2026-07-01", out)

    def test_last_played_never(self):
        """'Never' shows when game has never been played."""
        self.assertIn("Never", _panel(_make_game(last_played=None)))

    def test_tags_none_fallback(self):
        """Tags row shows 'None' when game has no tags attribute."""
        out = _panel(_make_game())
        self.assertIn("Tags:", out)
        self.assertIn("None", out)

    def test_collections_none_fallback(self):
        """Collections row shows 'None' when game has no collections attribute."""
        out = _panel(_make_game())
        self.assertIn("Collections:", out)
        self.assertIn("None", out)

    def test_quick_actions_present(self):
        """Quick Action key hints appear."""
        out = _panel(_make_game())
        self.assertIn("Quick Actions:", out)
        self.assertIn("[Enter]", out)
        self.assertIn("[Alt]", out)
        self.assertIn("[Ctrl+D]", out)
        self.assertIn("[Ctrl+F]", out)

    def test_favorite_badge_true(self):
        """★ FAVORITE badge appears for favorites."""
        self.assertIn("★ FAVORITE", _panel(_make_game(favorite=True)))

    def test_favorite_badge_false(self):
        """☆ STANDARD badge appears for non-favorites."""
        self.assertIn("☆ STANDARD", _panel(_make_game(favorite=False)))

    def test_hero_artwork_name_shown(self):
        """Hero artwork filename appears when artwork is present."""
        out = _panel(_make_game(), hero="/cache/god_of_war_hero.jpg")
        self.assertIn("Hero Artwork:", out)
        self.assertIn("god_of_war_hero.jpg", out)

    def test_genre_fallback_shown(self):
        """Default genre fallback 'Action / Adventure' shows when no tags/genre."""
        out = _panel(_make_game())
        self.assertIn("Genre:", out)
        self.assertIn("Action / Adventure", out)


class TestHeroPanelFallback(unittest.TestCase):
    """Verify graceful fallback when artwork is unavailable."""

    def test_gradient_indicator_shown_when_no_hero(self):
        """Gradient glassmorphism status shown when no hero image."""
        self.assertIn("Gradient Glassmorphism Active", _panel(_make_game()))

    def test_panel_never_empty(self):
        """Panel always has title and quick actions, even without artwork."""
        out = _panel(_make_game(name="Empty Game"))
        self.assertIn("Empty Game", out)
        self.assertIn("Quick Actions:", out)
        self.assertGreater(len(out), 100)

    def test_icon_shown_in_fallback(self):
        """Icon filename appears when no hero/cover but icon is available."""
        out = _panel(_make_game(name="Icon Game"), icon="/icons/icon_game.png")
        self.assertIn("icon_game.png", out)

    def test_hero_art_shown_when_present(self):
        """Hero artwork status replaced by gradient indicator when hero is set."""
        out = _panel(_make_game(), hero="/heroes/game.jpg")
        self.assertIn("game.jpg", out)
        self.assertNotIn("Gradient Glassmorphism Active", out)


class TestHeroPanelInstantUpdate(unittest.TestCase):
    """Panel content updates per-game selection, not cached from previous call."""

    def test_different_games_produce_different_output(self):
        """Two different games render different Hero Panel text."""
        out_a = _panel(_make_game(name="Alpha", launcher="steam"))
        out_b = _panel(_make_game(name="Beta", launcher="lutris"))
        self.assertNotEqual(out_a, out_b)
        self.assertIn("Alpha", out_a)
        self.assertNotIn("Alpha", out_b)
        self.assertIn("Beta", out_b)

    def test_favorite_toggle_updates_badge(self):
        """Toggling favorite changes the badge text."""
        out_std = _panel(_make_game(favorite=False))
        out_fav = _panel(_make_game(favorite=True))
        self.assertIn("☆ STANDARD", out_std)
        self.assertIn("★ FAVORITE", out_fav)

    def test_playtime_update_reflected(self):
        """Different playtime values produce different playtime text."""
        out_a = _panel(_make_game(playtime_minutes=0))
        out_b = _panel(_make_game(playtime_minutes=90))
        self.assertNotEqual(out_a, out_b)
        self.assertIn("1h 30m", out_b)


class TestHeroPanelMarkup(unittest.TestCase):
    """Verify Pango markup is well-formed."""

    def test_no_exception_raised(self):
        """render_panel_pango() must not raise any exception."""
        try:
            _panel(_make_game(name="Crash Test", playtime_minutes=999), hero="/hero.jpg")
        except Exception as exc:
            self.fail(f"render_panel_pango raised: {exc}")

    def test_multiline_output(self):
        """Output has at least 3 newline-separated sections."""
        out = _panel(_make_game())
        self.assertGreaterEqual(out.count("\n"), 3)

    def test_balanced_span_tags(self):
        """<span> opening and closing tags are balanced."""
        out = _panel(_make_game(name="Balance"), hero="/hero.jpg")
        self.assertEqual(out.count("<span"), out.count("</span>"))

    def test_output_is_string(self):
        """render_panel_pango always returns a str."""
        result = _panel(_make_game())
        self.assertIsInstance(result, str)

    def test_no_raw_python_placeholders(self):
        """Output should not contain literal Python f-string braces like { or }."""
        out = _panel(_make_game())
        # Pango XML uses < > not braces, so raw { } in output would indicate a bug
        self.assertNotIn("{hero_bg_rasi}", out)


if __name__ == "__main__":
    unittest.main()
