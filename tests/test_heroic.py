"""Unit and integration tests for Heroic Games Launcher provider and launcher."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from gamedeck.launchers.heroic import HeroicLauncher, launch as launch_heroic
from gamedeck.models import Game
from gamedeck.provider_manager import ProviderManager
from gamedeck.providers import Provider
from gamedeck.providers.heroic import HeroicProvider, get_games


class TestHeroicSupport(unittest.TestCase):
    """Test suite for Heroic Games Launcher provider and backend."""

    def test_protocol_conformance(self) -> None:
        """Verify that HeroicProvider conforms to the Provider protocol."""
        self.assertTrue(isinstance(HeroicProvider(), Provider))

    def test_legendary_epic_games_parsing(self) -> None:
        """Verify parsing of Legendary Epic Games Store installed.json metadata."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            legendary_dir = root / "legendaryConfig" / "legendary"
            legendary_dir.mkdir(parents=True)

            installed_json = legendary_dir / "installed.json"
            installed_data = {
                "Sugar": {
                    "app_name": "Sugar",
                    "title": "Grand Theft Auto V",
                    "install_path": str(root / "Games" / "GTAV"),
                    "executable": "PlayGTAV.exe",
                    "is_installed": True,
                    "version": "1.0.0",
                },
                "Salt": {
                    "app_name": "Salt",
                    "title": "Death Stranding",
                    "install_path": str(root / "Games" / "DeathStranding"),
                    "is_installed": True,
                },
            }
            with installed_json.open("w", encoding="utf-8") as f:
                json.dump(installed_data, f)

            provider = HeroicProvider(heroic_roots=[root])
            games = provider.get_games()

            self.assertEqual(len(games), 2)
            names = [g.name for g in games]
            self.assertIn("Grand Theft Auto V", names)
            self.assertIn("Death Stranding", names)

            gta = next(g for g in games if g.name == "Grand Theft Auto V")
            self.assertEqual(gta.source, "heroic")
            self.assertEqual(gta.launcher, "heroic")
            self.assertEqual(gta.appid, "Sugar")
            self.assertEqual(gta.id, "heroic_Sugar")

    def test_gog_and_nile_store_parsing(self) -> None:
        """Verify parsing of GOG and Amazon Prime Nile stores."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            # GOG store setup
            gog_dir = root / "gog_store"
            gog_dir.mkdir(parents=True)
            gog_json = gog_dir / "installed.json"
            with gog_json.open("w", encoding="utf-8") as f:
                json.dump(
                    {
                        "installed": [
                            {
                                "appName": "1424372224",
                                "title": "Cyberpunk 2077",
                                "install_path": str(root / "Cyberpunk2077"),
                            }
                        ]
                    },
                    f,
                )

            # Nile Amazon store setup
            nile_dir = root / "nile_store"
            nile_dir.mkdir(parents=True)
            nile_json = nile_dir / "installed.json"
            with nile_json.open("w", encoding="utf-8") as f:
                json.dump(
                    {
                        "installed": [
                            {
                                "id": "amzn1.adg.product.12345",
                                "title": "Fallout: New Vegas",
                                "install_path": str(root / "FalloutNV"),
                            }
                        ]
                    },
                    f,
                )

            provider = HeroicProvider(heroic_roots=[root])
            games = provider.get_games()

            self.assertEqual(len(games), 2)
            titles = [g.name for g in games]
            self.assertIn("Cyberpunk 2077", titles)
            self.assertIn("Fallout: New Vegas", titles)

    def test_heroic_priority_deduplication(self) -> None:
        """Verify priority hierarchy: Steam (50) > Heroic (40) > Lutris (30)."""
        g_steam = Game(id="steam_1091500", name="Cyberpunk 2077", source="steam", launcher="steam", appid="1091500")
        g_heroic = Game(id="heroic_1424372224", name="Cyberpunk 2077", source="heroic", launcher="heroic", appid="1424372224")
        g_lutris = Game(id="lutris_cp2077", name="Cyberpunk 2077", source="lutris", launcher="lutris", appid="cyberpunk-2077")

        manager = ProviderManager()

        # Steam beats Heroic and Lutris
        merged_all = manager.merge_and_deduplicate([g_lutris, g_heroic, g_steam])
        self.assertEqual(len(merged_all), 1)
        self.assertEqual(merged_all[0].source, "steam")

        # Heroic beats Lutris
        merged_hl = manager.merge_and_deduplicate([g_lutris, g_heroic])
        self.assertEqual(len(merged_hl), 1)
        self.assertEqual(merged_hl[0].source, "heroic")

    @patch("shutil.which")
    @patch("subprocess.Popen")
    def test_heroic_launcher_dispatch(self, mock_popen: MagicMock, mock_which: MagicMock) -> None:
        """Verify that HeroicLauncher executes heroic --no-gui heroic://launch/<app>."""
        mock_which.side_effect = lambda cmd: "/usr/bin/heroic" if cmd == "heroic" else None

        game = Game(id="heroic_Sugar", name="Grand Theft Auto V", source="heroic", launcher="heroic", appid="Sugar")

        launcher = HeroicLauncher()
        launcher.launch(game)

        mock_popen.assert_called_once()
        cmd = mock_popen.call_args[0][0]
        self.assertEqual(cmd, ["/usr/bin/heroic", "--no-gui", "heroic://launch/Sugar"])


if __name__ == "__main__":
    unittest.main()
