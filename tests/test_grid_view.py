"""Unit tests for GameDeck Grid View and extensible multi-view architecture."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from gamedeck.database import MetadataCache
from gamedeck.models import Game
from gamedeck.ui.artwork_resolver import ArtworkResolver, FALLBACK_ICON
from gamedeck.ui.rofi import RofiUI
from gamedeck.ui.views import (
    CardStyle,
    CompactCardStyle,
    GridViewRenderer,
    HeroCardStyle,
    LandscapeCardStyle,
    ListViewRenderer,
    PortraitCardStyle,
    ViewManager,
    ViewMode,
    calculate_responsive_columns,
    get_card_style,
)


class TestGridViewArchitecture(unittest.TestCase):
    """Test suite verifying multi-view manager, card styles, and grid renderer."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_gamedeck.db"
        self.cache = MetadataCache(db_path=self.db_path)

        self.sample_game = Game(
            id="filesystem_black-myth-wukong",
            name="Black Myth - Wukong",
            source="filesystem",
            launcher="lutris",
            executable=Path("/mnt/windows/Games/Black Myth - Wukong/b1/Binaries/Win64/b1-Win64-Shipping.exe"),
            favorite=True,
            installed=True,
            appid="black-myth-wukong",
        )

        self.steam_game = Game(
            id="steam_1091500",
            name="Cyberpunk 2077",
            source="steam",
            launcher="steam",
            appid="1091500",
            favorite=False,
            installed=True,
        )

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_view_mode_enum_and_switching(self) -> None:
        """Verify ViewManager supports switching between List View and Grid View."""
        vm = ViewManager(default_view=ViewMode.LIST, db_cache=self.cache)
        self.assertEqual(vm.active_mode, ViewMode.LIST)

        vm.switch_to_grid()
        self.assertEqual(vm.active_mode, ViewMode.GRID)

        # Verify saved state persisted to SQLite
        self.assertEqual(self.cache.get_ui_state("active_view"), "grid")

        vm.switch_to_list()
        self.assertEqual(vm.active_mode, ViewMode.LIST)
        self.assertEqual(self.cache.get_ui_state("active_view"), "list")

    def test_view_manager_persists_and_restores_from_db(self) -> None:
        """Verify newly created ViewManager restores active view from SQLite database."""
        self.cache.set_ui_state("active_view", "grid")

        vm = ViewManager(default_view=ViewMode.LIST, db_cache=self.cache)
        self.assertEqual(vm.active_mode, ViewMode.GRID)

    def test_artwork_priority_resolution(self) -> None:
        """Verify multi-tier artwork fallback hierarchy: Hero -> Cover -> Capsule -> Icon -> Theme."""
        resolver = ArtworkResolver(cache_dir=Path(self.tmp_dir.name) / "artwork")

        # 1. Fallback to theme icon when no cache exists
        icon = resolver.resolve_grid_cover(self.sample_game)
        self.assertEqual(icon, "lutris")

        # 2. Add local cover art to cache and verify it takes priority
        covers_dir = resolver.cache_dir / "covers"
        covers_dir.mkdir(parents=True, exist_ok=True)
        test_cover = covers_dir / f"{self.sample_game.id}.png"
        test_cover.write_bytes(b"PNG_FAKE_DATA")

        # Clear memory cache to test disk resolution
        resolver._thumbnail_cache.clear()
        resolved_cover = resolver.resolve_grid_cover(self.sample_game)
        self.assertEqual(resolved_cover, str(test_cover))

        # 3. Add hero banner and test hero preference
        heroes_dir = resolver.cache_dir / "heroes"
        heroes_dir.mkdir(parents=True, exist_ok=True)
        test_hero = heroes_dir / f"{self.sample_game.id}.jpg"
        test_hero.write_bytes(b"JPG_FAKE_DATA")

        resolver._thumbnail_cache.clear()
        resolved_hero = resolver.resolve_grid_cover(self.sample_game, preferred_type="hero")
        self.assertEqual(resolved_hero, str(test_hero))

    def test_card_styles_formatting(self) -> None:
        """Verify card layout formatting across Portrait, Compact, Landscape, Hero, and Carousel."""
        portrait = get_card_style("portrait")
        self.assertIsInstance(portrait, PortraitCardStyle)
        self.assertEqual(portrait.aspect_ratio, "2:3")
        label = portrait.format_card_label(self.sample_game)
        self.assertTrue(label.startswith("★ "))
        self.assertIn("Black Myth - Wukong", label)
        self.assertIn("[Lutris]", label)

        compact = get_card_style("compact")
        self.assertIsInstance(compact, CompactCardStyle)
        self.assertEqual(compact.aspect_ratio, "1:1")

        landscape = get_card_style("landscape")
        self.assertIsInstance(landscape, LandscapeCardStyle)
        self.assertEqual(landscape.aspect_ratio, "16:9")

        hero = get_card_style("hero")
        self.assertIsInstance(hero, HeroCardStyle)

    def test_calculate_responsive_columns(self) -> None:
        """Verify dynamic column calculations for small, medium, and large layouts."""
        # Fixed configured columns override
        self.assertEqual(calculate_responsive_columns(10, configured_columns=4), 4)

        # Small display width or small library count
        self.assertEqual(calculate_responsive_columns(4, window_width=900), 3)

        # Medium display width
        self.assertEqual(calculate_responsive_columns(20, window_width=1600), 5)

        # Large display width
        self.assertEqual(calculate_responsive_columns(50, window_width=2200), 6)

    def test_grid_view_rasi_theme_generation(self) -> None:
        """Verify generated RASI theme contains frosted-glass tokens, rounded corners, and green accent."""
        renderer = GridViewRenderer(columns=5, accent_color="#00e699")
        card_style = PortraitCardStyle()
        rasi = renderer.generate_grid_theme_str(5, card_style)

        self.assertIn("accent: #00e699;", rasi)
        self.assertIn("columns: 5;", rasi)
        self.assertIn("border-radius: 16px;", rasi)
        self.assertIn("background-color: #0c1412f2;", rasi)
        self.assertIn("element selected", rasi)
        self.assertIn("border-color: #00e699;", rasi)

    def test_grid_renderer_details_panel_formatting(self) -> None:
        """Verify rich details panel formats launcher, platform, playtime, and wine version."""
        renderer = GridViewRenderer()
        details_str = renderer._build_details_panel(self.sample_game)

        self.assertIn("Black Myth - Wukong", details_str)
        self.assertIn("Source:</b> Filesystem", details_str)
        self.assertIn("Launcher:</b> lutris", details_str)
        self.assertIn("Playtime:", details_str)

    @patch("subprocess.run")
    @patch("shutil.which", return_value="/usr/bin/rofi")
    def test_grid_renderer_keyboard_shortcuts(self, mock_which: MagicMock, mock_run: MagicMock) -> None:
        """Verify return codes 11 (Ctrl+1) and 12 (Ctrl+2) trigger view switching in GridViewRenderer."""
        renderer = GridViewRenderer()
        games = [self.sample_game, self.steam_game]

        # Simulate Ctrl+1 (returncode 11)
        mock_run.return_value = MagicMock(returncode=11, stdout="")
        _, code, trigger = renderer.render(games)
        self.assertEqual(code, 11)
        self.assertEqual(trigger, "switch_view_list")

        # Simulate Alt+Return on first game (returncode 10)
        mock_run.return_value = MagicMock(returncode=10, stdout="0\n")
        selected, code, trigger = renderer.render(games)
        self.assertEqual(selected, self.sample_game)
        self.assertEqual(trigger, "action_menu")

        # Simulate Enter on second game (returncode 0)
        mock_run.return_value = MagicMock(returncode=0, stdout="1\n")
        selected, code, trigger = renderer.render(games)
        self.assertEqual(selected, self.steam_game)
        self.assertEqual(trigger, "launch")

    @patch("subprocess.run")
    @patch("shutil.which", return_value="/usr/bin/rofi")
    def test_rofi_ui_view_switching_integration(self, mock_which: MagicMock, mock_run: MagicMock) -> None:
        """Verify RofiUI seamless switching between List and Grid view without restarting."""
        ui = RofiUI(default_view="list", db_cache=self.cache)
        games = [self.sample_game, self.steam_game]

        # First call triggers Ctrl+2 to switch to Grid, second call selects Black Myth
        mock_run.side_effect = [
            MagicMock(returncode=12, stdout=""),  # Ctrl+2: switch to grid
            MagicMock(returncode=0, stdout="0\n"), # Enter: launch Black Myth in grid
        ]

        result = ui.select(games)
        self.assertEqual(result, self.sample_game)
        self.assertEqual(ui.active_view_mode, ViewMode.GRID)


if __name__ == "__main__":
    unittest.main()
