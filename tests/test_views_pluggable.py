"""Unit and integration tests for the pluggable LibraryView architecture in GameDeck."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from gamedeck.database import MetadataCache
from gamedeck.models import Game
from gamedeck.ui.views import (
    CarouselView,
    CompactView,
    GridView,
    HeroView,
    LibraryView,
    ListView,
    ViewManager,
    ViewMode,
)


class TestPluggableViews(unittest.TestCase):
    """Test suite for the pluggable LibraryView system, ViewManager registry, and view transparency."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.cache = MetadataCache(db_path=self.root / "metadata.db")
        self.sample_game = Game(
            id="steam_1245620",
            name="Elden Ring",
            source="steam",
            launcher="steam",
            appid="1245620",
            favorite=True,
            playtime_minutes=240,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_library_view_interface_contract(self) -> None:
        """Verify all view classes implement the LibraryView abstract interface."""
        for view_cls in (ListView, GridView, CompactView, HeroView, CarouselView):
            self.assertTrue(issubclass(view_cls, LibraryView))
            instance = view_cls()
            self.assertTrue(hasattr(instance, "name"))
            self.assertTrue(hasattr(instance, "display_name"))
            self.assertTrue(hasattr(instance, "render"))

    def test_view_registry_and_lookup(self) -> None:
        """Verify ViewManager registers built-in views and allows dynamic registration."""
        vm = ViewManager(db_cache=self.cache)

        # Built-in views registered
        self.assertIsNotNone(vm.get_view("list"))
        self.assertIsNotNone(vm.get_view("grid"))
        self.assertIsNotNone(vm.get_view("compact"))
        self.assertIsNotNone(vm.get_view("hero"))
        self.assertIsNotNone(vm.get_view("carousel"))

        # Custom view registration
        class CustomShowcaseView(LibraryView):
            name = "custom_showcase"
            display_name = "Custom Showcase"

            def render(self, games, **kwargs):
                return (games[0] if games else None, 0, "launch")

        vm.register_view(CustomShowcaseView())
        self.assertIsNotNone(vm.get_view("custom_showcase"))

    def test_view_switching_one_setting(self) -> None:
        """Verify switching views requires changing only one setting and persists to SQLite."""
        vm = ViewManager(default_view="list", db_cache=self.cache)
        self.assertEqual(vm.active_mode, ViewMode.LIST)
        self.assertEqual(vm.active_view.name, "list")

        # Switch to Hero view
        vm.switch_to("hero")
        self.assertEqual(vm.active_mode, ViewMode.HERO)
        self.assertEqual(vm.active_view.name, "hero")
        self.assertEqual(self.cache.get_ui_state("active_view"), "hero")

        # Switch to Compact view
        vm.switch_to("compact")
        self.assertEqual(vm.active_mode, ViewMode.COMPACT)
        self.assertEqual(vm.active_view.name, "compact")
        self.assertEqual(self.cache.get_ui_state("active_view"), "compact")

        # Switch to Carousel view
        vm.switch_to("carousel")
        self.assertEqual(vm.active_mode, ViewMode.CAROUSEL)
        self.assertEqual(vm.active_view.name, "carousel")
        self.assertEqual(self.cache.get_ui_state("active_view"), "carousel")

    def test_rest_of_gamedeck_view_transparency(self) -> None:
        """Verify callers only invoke view_manager.render() without knowing which view is active."""
        vm = ViewManager(default_view="grid", db_cache=self.cache)

        with patch.object(GridView, "render", return_value=(self.sample_game, 0, "launch")) as mock_grid:
            res, code, trigger = vm.render(games=[self.sample_game])
            self.assertEqual(res, self.sample_game)
            self.assertEqual(trigger, "launch")
            mock_grid.assert_called_once()

        vm.switch_to("list")
        with patch.object(ListView, "render", return_value=(self.sample_game, 0, "launch")) as mock_list:
            res, code, trigger = vm.render(games=[self.sample_game])
            self.assertEqual(res, self.sample_game)
            self.assertEqual(trigger, "launch")
            mock_list.assert_called_once()


if __name__ == "__main__":
    unittest.main()
