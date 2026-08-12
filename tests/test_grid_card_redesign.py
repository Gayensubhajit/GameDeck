"""Unit tests for redesigned Grid View cards."""

from __future__ import annotations

import unittest

from gamedeck.models import Game
from gamedeck.ui.views.cards import PortraitCardStyle, get_card_style
from gamedeck.ui.views.grid import GridView


class TestGridCardRedesign(unittest.TestCase):
    """Test Grid View card elements, badge pill formatting, rounded corners, and focus states."""

    def setUp(self) -> None:
        self.grid_view = GridView()
        self.card_style = get_card_style("portrait")

    def test_card_label_formatting_with_all_elements(self) -> None:
        """Verify cover, game title, launcher badge, favorite indicator, and optional playtime are included."""
        game = Game(
            id="test_g",
            name="Cyberpunk 2077",
            source="lutris",
            launcher="lutris",
            favorite=True,
            installed=True,
            playtime_minutes=750,
        )

        label = self.card_style.format_card_label(game, playtime_minutes=750)
        self.assertTrue(label.startswith("★ "))
        self.assertIn("Cyberpunk 2077", label)
        self.assertIn("[LUTRIS]", label)
        self.assertIn("⏱ 12h", label)

    def test_grid_theme_rasi_styling_tokens(self) -> None:
        """Verify RASI theme generator applies rounded corners (16px), subtle shadows, and glowing focus border."""
        rasi_str = self.grid_view.generate_grid_theme_str(columns=5, card_style=self.card_style)

        # 16px rounded corners on card elements
        self.assertIn("border-radius: 16px;", rasi_str)
        # 12px rounded corners on cover icons
        self.assertIn("border-radius: 12px;", rasi_str)

        # Glowing focus border & emerald highlight
        self.assertIn("background-color: #00e69928;", rasi_str)
        self.assertIn("border-color: #00e699;", rasi_str)

        # Spacing and typography
        self.assertIn('font: "Outfit SemiBold 10.5";', rasi_str)
        self.assertIn("spacing: 6px;", rasi_str)


if __name__ == "__main__":
    unittest.main()
