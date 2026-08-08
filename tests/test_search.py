"""Unit tests for the SearchIndex, tokenizer, and search engine package."""

from __future__ import annotations

import unittest
from pathlib import Path

from gamedeck.models import Game
from gamedeck.search import SearchIndex, SearchResult, index_games, normalize, search, tokenize


class TestTokenizer(unittest.TestCase):
    """Test tokenization, normalisation, acronyms, and aliases generation."""

    def test_normalize(self) -> None:
        self.assertEqual(normalize("Counter-Strike 2"), "counter strike 2")
        self.assertEqual(normalize("Black Myth: Wukong"), "black myth  wukong")
        self.assertEqual(normalize("Grand Theft Auto V"), "grand theft auto v")
        self.assertEqual(normalize(""), "")

    def test_tokenize_black_myth_wukong(self) -> None:
        tokens = tokenize("Black Myth: Wukong")
        self.assertIn("bmw", tokens)
        self.assertIn("blackmythwukong", tokens)
        self.assertIn("black", tokens)
        self.assertIn("myth", tokens)
        self.assertIn("wukong", tokens)

    def test_tokenize_grand_theft_auto_v(self) -> None:
        tokens = tokenize("Grand Theft Auto V")
        self.assertIn("gta", tokens)
        self.assertIn("gtav", tokens)
        self.assertIn("gta5", tokens)
        self.assertIn("v", tokens)
        self.assertIn("5", tokens)

    def test_tokenize_elden_ring(self) -> None:
        tokens = tokenize("Elden Ring")
        self.assertIn("er", tokens)
        self.assertIn("elden", tokens)
        self.assertIn("ring", tokens)
        self.assertIn("eldenring", tokens)

    def test_tokenize_counter_strike_2(self) -> None:
        tokens = tokenize("Counter-Strike 2")
        self.assertIn("cs", tokens)
        self.assertIn("cs2", tokens)
        self.assertIn("counterstrike2", tokens)

    def test_tokenize_with_appid_source_executable(self) -> None:
        tokens = tokenize(
            name="Portal 2",
            appid="620",
            source="steam",
            executable=Path("/home/user/games/portal2.exe"),
        )
        self.assertIn("portal", tokens)
        self.assertIn("620", tokens)
        self.assertIn("steam", tokens)
        self.assertIn("portal2", tokens)


class TestSearchIndex(unittest.TestCase):
    """Test SearchIndex ranking, abbreviation lookup, and matching behavior."""

    def setUp(self) -> None:
        self.games = [
            Game(id="steam_bmw", name="Black Myth: Wukong", source="steam", launcher="steam"),
            Game(id="steam_er", name="Elden Ring", source="steam", launcher="steam"),
            Game(id="lutris_gta5", name="Grand Theft Auto V", source="lutris", launcher="lutris"),
            Game(id="steam_cs2", name="Counter-Strike 2", source="steam", launcher="steam"),
            Game(id="native_portal2", name="Portal 2", source="native", launcher="native"),
            Game(id="heroic_cp2077", name="Cyberpunk 2077", source="heroic", launcher="heroic"),
        ]
        self.index = SearchIndex.build(self.games)

    def test_index_len(self) -> None:
        self.assertEqual(len(self.index), len(self.games))

    def test_exact_title_match(self) -> None:
        results = self.index.search("Elden Ring")
        self.assertTrue(len(results) > 0)
        self.assertEqual(results[0].game.name, "Elden Ring")
        self.assertEqual(results[0].score, 1.0)

    def test_abbreviation_bmw(self) -> None:
        results = self.index.search("BMW")
        self.assertTrue(len(results) > 0)
        self.assertEqual(results[0].game.name, "Black Myth: Wukong")
        self.assertGreaterEqual(results[0].score, 0.90)

    def test_abbreviation_er(self) -> None:
        results = self.index.search("ER")
        self.assertTrue(len(results) > 0)
        self.assertEqual(results[0].game.name, "Elden Ring")
        self.assertGreaterEqual(results[0].score, 0.90)

    def test_abbreviation_gtav(self) -> None:
        results = self.index.search("GTAV")
        self.assertTrue(len(results) > 0)
        self.assertEqual(results[0].game.name, "Grand Theft Auto V")
        self.assertGreaterEqual(results[0].score, 0.90)

    def test_abbreviation_gta5(self) -> None:
        results = self.index.search("GTA5")
        self.assertTrue(len(results) > 0)
        self.assertEqual(results[0].game.name, "Grand Theft Auto V")
        self.assertGreaterEqual(results[0].score, 0.90)

    def test_abbreviation_cs2(self) -> None:
        results = self.index.search("CS2")
        self.assertTrue(len(results) > 0)
        self.assertEqual(results[0].game.name, "Counter-Strike 2")
        self.assertGreaterEqual(results[0].score, 0.90)

    def test_partial_matching(self) -> None:
        results = self.index.search("Cyber")
        self.assertTrue(len(results) > 0)
        self.assertEqual(results[0].game.name, "Cyberpunk 2077")

    def test_case_insensitive_matching(self) -> None:
        lower_res = self.index.search("elden ring")
        upper_res = self.index.search("ELDEN RING")
        mixed_res = self.index.search("ElDeN rInG")
        self.assertEqual(lower_res[0].game.id, upper_res[0].game.id)
        self.assertEqual(lower_res[0].game.id, mixed_res[0].game.id)

    def test_punctuation_removal(self) -> None:
        results = self.index.search("Counter Strike")
        self.assertTrue(len(results) > 0)
        self.assertEqual(results[0].game.name, "Counter-Strike 2")

    def test_ranking_precedence(self) -> None:
        # Exact title match should outrank prefix/partial matches
        results = self.index.search("Portal 2")
        self.assertEqual(results[0].game.name, "Portal 2")
        self.assertEqual(results[0].score, 1.0)

    def test_limit(self) -> None:
        results = self.index.search("e", limit=2)
        self.assertLessEqual(len(results), 2)

    def test_empty_query(self) -> None:
        self.assertEqual(self.index.search(""), [])
        self.assertEqual(self.index.search("   "), [])
        self.assertEqual(self.index.search("!!!"), [])

    def test_empty_index(self) -> None:
        empty_idx = SearchIndex()
        self.assertEqual(empty_idx.search("BMW"), [])
        self.assertEqual(len(empty_idx), 0)


class TestSearchConvenienceFunctions(unittest.TestCase):
    """Test index_games and search helper functions."""

    def test_index_games_and_search_helpers(self) -> None:
        games = [
            Game(id="1", name="Black Myth: Wukong", source="steam", launcher="steam"),
            Game(id="2", name="Elden Ring", source="steam", launcher="steam"),
        ]
        idx = index_games(games)
        self.assertIsInstance(idx, SearchIndex)
        self.assertEqual(len(idx), 2)

        results = search(games, "BMW")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].game.name, "Black Myth: Wukong")


if __name__ == "__main__":
    unittest.main()
