"""Unit and integration tests for Recently Played games tracking and sorting."""

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from gamedeck.config import Settings
from gamedeck.database import MetadataCache
from gamedeck.models import Game
from gamedeck.provider_manager import sort_games_with_recents


class TestRecentlyPlayed(unittest.TestCase):
    """Test suite for Recently Played game tracking, sorting, and configurable limits."""

    def test_sort_order_favorites_then_recents_then_alphabetical(self) -> None:
        """Verify sorting hierarchy: Favorites -> Recents (newest first) -> Alphabetical."""
        g_fav = Game(id="g_fav", name="Zelda", source="native", launcher="native", favorite=True)
        g_recent_new = Game(
            id="g_new",
            name="Cyberpunk 2077",
            source="steam",
            launcher="steam",
            favorite=False,
            last_played="2026-08-08T00:30:00+00:00",
        )
        g_recent_old = Game(
            id="g_old",
            name="Apex Legends",
            source="steam",
            launcher="steam",
            favorite=False,
            last_played="2026-08-01T12:00:00+00:00",
        )
        g_unplayed_a = Game(id="g_a", name="Baldur's Gate 3", source="steam", launcher="steam", favorite=False)
        g_unplayed_m = Game(id="g_m", name="Minecraft", source="native", launcher="native", favorite=False)

        sorted_games = sort_games_with_recents(
            [g_unplayed_m, g_recent_old, g_fav, g_unplayed_a, g_recent_new],
            recent_limit=5,
        )

        names = [g.name for g in sorted_games]
        expected_order = [
            "Zelda",  # 1. Favorite
            "Cyberpunk 2077",  # 2. Most recent
            "Apex Legends",  # 3. Older recent
            "Baldur's Gate 3",  # 4. Unplayed (alphabetical 'B')
            "Minecraft",  # 5. Unplayed (alphabetical 'M')
        ]
        self.assertEqual(names, expected_order)

    def test_configurable_recent_limit(self) -> None:
        """Verify that recent_limit limits the number of recent games prioritized above alphabetical."""
        g1 = Game(id="g1", name="Game 1", source="steam", launcher="steam", last_played="2026-08-08T01:00:00")
        g2 = Game(id="g2", name="Game 2", source="steam", launcher="steam", last_played="2026-08-08T02:00:00")
        g3 = Game(id="g3", name="Game 3", source="steam", launcher="steam", last_played="2026-08-08T03:00:00")
        g_alpha = Game(id="ga", name="A Alpha Game", source="steam", launcher="steam")

        # When recent_limit is 1, only the single newest recent game appears above "A Alpha Game"
        sorted_games = sort_games_with_recents([g_alpha, g1, g2, g3], recent_limit=1)

        # Newest recent game is Game 3
        self.assertEqual(sorted_games[0].name, "Game 3")
        # Next is alphabetical 'A Alpha Game'
        self.assertEqual(sorted_games[1].name, "A Alpha Game")

    def test_database_timestamp_tracking(self) -> None:
        """Verify that record_launch stores valid ISO timestamps in SQLite."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "metadata.db"
            cache = MetadataCache(db_path=db_path)

            game_id = "steam_730"
            cache.record_launch(game_id)

            meta = cache.get_metadata(game_id)
            self.assertIsNotNone(meta)
            self.assertIsNotNone(meta.last_played)
            self.assertEqual(meta.launch_count, 1)

            # Check ISO format
            parsed_dt = datetime.fromisoformat(meta.last_played)
            self.assertIsNotNone(parsed_dt)

            # Retrieve recently played IDs
            recents = cache.get_recently_played_ids(limit=5)
            self.assertIn(game_id, recents)


if __name__ == "__main__":
    unittest.main()
