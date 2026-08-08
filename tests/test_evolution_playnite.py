"""Unit tests verifying the 6-phase evolution features for GameDeck."""

import unittest
from pathlib import Path

from gamedeck.models import Game
from gamedeck.search.index import SearchIndex
from gamedeck.collections import (
    CollectionManager,
    LinuxNativeCollectionGenerator,
    ControllerCollectionGenerator,
)
from gamedeck.details import format_rofi_mesg, GameDetails
from gamedeck.ui.views.cards import (
    PortraitCardStyle,
    DeckCardStyle,
    get_card_style,
)
from gamedeck.plugins import (
    PluginRegistry,
    BaseMetadataSourcePlugin,
    BaseArtworkSourcePlugin,
    BaseViewPlugin,
    BaseStatisticsPlugin,
)
from gamedeck.plugins.builtins import SteamGridDBArtworkPlugin
from gamedeck.ui.views import ViewManager, LibraryView


class TestEvolutionFeatures(unittest.TestCase):
    """Test suite covering search boosting, smart collections, details, cards, and plugins."""

    def setUp(self) -> None:
        self.games = [
            Game(
                id="steam_730",
                name="Counter-Strike 2",
                source="steam",
                launcher="steam",
                favorite=True,
                last_played="2026-08-01T12:00:00+00:00",
                launch_count=20,
                installed=True,
                playtime_minutes=360,
                platform="Linux Native",
            ),
            Game(
                id="steam_1245620",
                name="Elden Ring",
                source="steam",
                launcher="steam",
                favorite=False,
                last_played="2026-07-20T10:00:00+00:00",
                launch_count=2,
                installed=True,
                playtime_minutes=120,
                notes="Controller recommended, soulslike",
                platform="Windows",
            ),
            Game(
                id="native_supertuxkart",
                name="SuperTuxKart",
                source="native",
                launcher="native",
                favorite=False,
                last_played=None,
                launch_count=0,
                installed=True,
                platform="Linux Native",
            ),
        ]

    # --- Phase 1: Search Boosting & Smart Collections ---

    def test_search_engagement_boosting(self) -> None:
        """Verify that favorite and recently played games receive score boosts."""
        idx = SearchIndex.build(self.games)
        # Search for 'strike' (CS2 is favorite + recent + frequent)
        cs_res = idx.search("Counter")
        self.assertTrue(len(cs_res) > 0)
        self.assertGreaterEqual(cs_res[0].score, 0.85)

    def test_search_in_collections(self) -> None:
        """Verify simultaneous search across games and collection names."""
        idx = SearchIndex.build(self.games)
        collections = ["Favorites", "Recently Played", "Linux Native", "Steam"]
        results, matched_colls = idx.search_in_collections("Steam", collections)
        self.assertIn("Steam", matched_colls)
        self.assertTrue(any(r.game.id == "steam_730" for r in results))

    def test_linux_native_collection(self) -> None:
        """Verify LinuxNativeCollection filters games running without compatibility layers."""
        gen = LinuxNativeCollectionGenerator()
        coll = gen.generate(self.games, metadata_cache=None)  # type: ignore
        game_ids = {g.id for g in coll.games}
        self.assertIn("native_supertuxkart", game_ids)

    def test_controller_collection(self) -> None:
        """Verify ControllerCollection matches games with controller support signals."""
        gen = ControllerCollectionGenerator()
        coll = gen.generate(self.games, metadata_cache=None)  # type: ignore
        game_ids = {g.id for g in coll.games}
        self.assertIn("steam_1245620", game_ids)  # Notes contain 'controller'

    # --- Phase 2: Live Details Helper ---

    def test_format_rofi_mesg_output(self) -> None:
        """Verify format_rofi_mesg produces a rich single-line status bar string."""
        msg = format_rofi_mesg(self.games[0])
        self.assertIn("Counter-Strike 2", msg)
        self.assertIn("[STEAM]", msg)
        self.assertIn("★", msg)

    # --- Phase 3: Card Layout Improvements ---

    def test_card_style_playtime_and_installed(self) -> None:
        """Verify card labels contain playtime and installed indicator."""
        style = PortraitCardStyle()
        label = style.format_card_label(self.games[0], playtime_minutes=360)
        self.assertIn("Counter-Strike 2", label)
        self.assertIn("[STEAM]", label)
        self.assertIn("•", label)  # Installed dot
        self.assertIn("⏱ 6h", label)  # Playtime formatted

    def test_deck_card_style_remains_clean(self) -> None:
        """Verify DeckCardStyle stays clean for console gamepad aesthetics."""
        deck_style = DeckCardStyle()
        label = deck_style.format_card_label(self.games[0])
        self.assertEqual(label.strip(), "Counter-Strike 2")

    # --- Phase 4: Thumbnail Generation ---

    def test_generate_thumbnails_empty_or_mock(self) -> None:
        """Verify generate_thumbnails handles missing files gracefully without error."""
        from gamedeck.metadata_manager import MetadataManager
        mgr = MetadataManager()
        thumbs = mgr.generate_thumbnails(self.games)
        self.assertIsInstance(thumbs, dict)

    # --- Phase 5: Plugin Architecture ---

    def test_plugin_registry_extensions(self) -> None:
        """Verify PluginRegistry handles metadata, artwork, view, and statistics plugins."""
        reg = PluginRegistry()

        class DummyArtworkPlugin(BaseArtworkSourcePlugin):
            name = "dummy_art"
            display_name = "Dummy Artwork"
            priority = 20

            def is_available(self) -> bool:
                return True

            def fetch_artwork_urls(self, game: Game, art_type: str) -> list[str]:
                return ["https://example.com/art.png"]

        plugin = DummyArtworkPlugin()
        reg.register_artwork_source(plugin)
        sources = reg.get_all_artwork_sources()
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0].name, "dummy_art")

    def test_view_manager_register_external_view(self) -> None:
        """Verify ViewManager accepts external custom views."""
        vm = ViewManager()

        class CustomView(LibraryView):
            name = "custom_mosaic"
            display_name = "Custom Mosaic"

            def render(self, games, **kwargs):
                return (None, 0, "cancel")

        custom_v = CustomView()
        vm.register_external_view(custom_v)
        retrieved = vm.get_view("custom_mosaic")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.name, "custom_mosaic")

    def test_steamgriddb_builtin_plugin(self) -> None:
        """Verify SteamGridDBArtworkPlugin implements BaseArtworkSourcePlugin contract."""
        sgdb_plugin = SteamGridDBArtworkPlugin(api_key="")
        self.assertEqual(sgdb_plugin.name, "steamgriddb")
        self.assertIsInstance(sgdb_plugin.is_available(), bool)
        urls = sgdb_plugin.fetch_artwork_urls(self.games[0], "hero")
        self.assertIsInstance(urls, list)


if __name__ == "__main__":
    unittest.main()
