"""Unit and integration tests for Favorites system and star indicators."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from gamedeck.database import MetadataCache
from gamedeck.models import Game
from gamedeck.provider_manager import ProviderManager
from gamedeck.ui.rofi import RofiUI


class TestFavorites(unittest.TestCase):
    """Test suite for Favorites persistence, star indicator, and sorting."""

    def test_favorites_appear_first_in_sorting(self) -> None:
        """Verify that favorite games appear first regardless of alphabetical position."""
        g1 = Game(id="g1", name="Apex Legends", source="steam", launcher="steam", favorite=False)
        g2 = Game(id="g2", name="Zelda", source="native", launcher="native", favorite=True)
        g3 = Game(id="g3", name="Cyberpunk 2077", source="steam", launcher="steam", favorite=False)

        manager = ProviderManager()
        sorted_games = manager.merge_and_deduplicate([g1, g2, g3])

        # Zelda is favorite -> must be index 0
        self.assertEqual(sorted_games[0].name, "Zelda")
        self.assertTrue(sorted_games[0].favorite)
        self.assertEqual(sorted_games[1].name, "Apex Legends")
        self.assertEqual(sorted_games[2].name, "Cyberpunk 2077")

    def test_star_indicator_in_rofi_payload(self) -> None:
        """Verify that favorite games receive the star indicator in Rofi."""
        g_fav = Game(id="f1", name="Black Myth - Wukong", source="lutris", launcher="lutris", favorite=True)
        g_norm = Game(id="n1", name="Counter-Strike 2", source="steam", launcher="steam", favorite=False)

        ui = RofiUI()
        with patch("shutil.which", return_value="/usr/bin/rofi"), patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="0\n")
            ui.select([g_fav, g_norm])

            mock_run.assert_called_once()
            input_payload = mock_run.call_args[1]["input"]
            lines = input_payload.splitlines()

            # Star indicator should be in first line
            self.assertTrue(lines[0].startswith("★  Black Myth - Wukong"))
            # Normal game should not have star indicator
            self.assertTrue(lines[1].startswith("Counter-Strike 2"))

    def test_toggle_favorite_persistence(self) -> None:
        """Verify toggle_favorite persists properly in SQLite database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "metadata.db"
            cache = MetadataCache(db_path=db_path)

            game_id = "steam_1245620"

            # Toggle 1: False -> True
            is_fav1 = cache.toggle_favorite(game_id)
            self.assertTrue(is_fav1)
            self.assertIn(game_id, cache.get_favorites())

            # Toggle 2: True -> False
            is_fav2 = cache.toggle_favorite(game_id)
            self.assertFalse(is_fav2)
            self.assertNotIn(game_id, cache.get_favorites())


if __name__ == "__main__":
    unittest.main()
