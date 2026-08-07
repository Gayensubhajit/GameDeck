"""Unit and integration tests for Native Linux desktop entry provider."""

import tempfile
import unittest
from pathlib import Path

from gamedeck.models import Game
from gamedeck.provider_manager import ProviderManager
from gamedeck.providers import Provider
from gamedeck.providers.native import NativeProvider, get_games


class TestNativeProvider(unittest.TestCase):
    """Test suite for Native Linux desktop entry provider."""

    def test_protocol_conformance(self) -> None:
        """Verify that NativeProvider conforms to the Provider protocol."""
        self.assertTrue(isinstance(NativeProvider(), Provider))

    def test_desktop_game_parsing(self) -> None:
        """Verify parsing of valid native .desktop game files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            game_desktop = root / "supergame.desktop"
            game_desktop.write_text(
                """[Desktop Entry]
Name=Super Tux
Exec=/usr/bin/supertux2 -f
Icon=supertux2
Type=Application
Categories=Game;ActionGame;
""",
                encoding="utf-8",
            )

            provider = NativeProvider(app_dirs=[root])
            games = provider.get_games()

            self.assertEqual(len(games), 1)
            g = games[0]
            self.assertEqual(g.name, "Super Tux")
            self.assertEqual(g.source, "native")
            self.assertEqual(g.launcher, "native")
            self.assertEqual(g.appid, "supergame")
            self.assertEqual(g.id, "native_supergame")

    def test_ignore_launchers_and_utilities(self) -> None:
        """Verify that store launchers, emulators, and utilities are filtered out."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            # Store launchers
            (root / "steam.desktop").write_text("[Desktop Entry]\nName=Steam\nCategories=Game;\n", encoding="utf-8")
            (root / "lutris.desktop").write_text("[Desktop Entry]\nName=Lutris\nCategories=Game;\n", encoding="utf-8")
            (root / "heroic.desktop").write_text("[Desktop Entry]\nName=Heroic\nCategories=Game;\n", encoding="utf-8")
            (root / "com.usebottles.bottles.desktop").write_text("[Desktop Entry]\nName=Bottles\nCategories=Game;\n", encoding="utf-8")
            (root / "com.libretro.RetroArch.desktop").write_text("[Desktop Entry]\nName=RetroArch\nCategories=Game;\n", encoding="utf-8")

            # Utilities & Tools
            (root / "goverlay.desktop").write_text("[Desktop Entry]\nName=GOverlay\nCategories=Game;\n", encoding="utf-8")
            (root / "antimicrox.desktop").write_text("[Desktop Entry]\nName=AntiMicroX\nCategories=Game;\n", encoding="utf-8")
            (root / "ksirkskineditor.desktop").write_text("[Desktop Entry]\nName=Skin Editor\nCategories=Game;\n", encoding="utf-8")

            # Non-game app
            (root / "firefox.desktop").write_text("[Desktop Entry]\nName=Firefox\nCategories=Network;WebBrowser;\n", encoding="utf-8")

            # Hidden / NoDisplay game
            (root / "hiddengame.desktop").write_text("[Desktop Entry]\nName=Hidden Game\nCategories=Game;\nNoDisplay=true\n", encoding="utf-8")

            provider = NativeProvider(app_dirs=[root])
            games = provider.get_games()
            self.assertEqual(len(games), 0)

    def test_priority_hierarchy_deduplication(self) -> None:
        """Verify that Native (20) beats Filesystem (10), and Lutris (30) beats Native (20)."""
        g_lutris = Game(id="lutris_mari0", name="mari0", source="lutris", launcher="lutris", appid="mari0")
        g_native = Game(id="native_mari0", name="mari0", source="native", launcher="native", appid="mari0")
        g_fs = Game(id="fs_mari0", name="mari0", source="filesystem", launcher="wine", appid="mari0")

        manager = ProviderManager()

        # Native beats Filesystem
        merged_nf = manager.merge_and_deduplicate([g_fs, g_native])
        self.assertEqual(len(merged_nf), 1)
        self.assertEqual(merged_nf[0].source, "native")

        # Lutris beats Native
        merged_ln = manager.merge_and_deduplicate([g_native, g_lutris])
        self.assertEqual(len(merged_ln), 1)
        self.assertEqual(merged_ln[0].source, "lutris")


if __name__ == "__main__":
    unittest.main()
