"""Unit tests for Launch Profiles system (Lutris, Wine, Steam, Proton Experimental) and persistence."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gamedeck.database import MetadataCache
from gamedeck.models import Game
from gamedeck.profiles import LaunchProfile, ProfileManager, get_profiles_for_game


class TestLaunchProfilesSystem(unittest.TestCase):
    """Test launch profile generation across runners, profile switching, and SQLite persistence."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.cache = MetadataCache(db_path=self.root / "metadata.db")
        self.prof_manager = ProfileManager(metadata_cache=self.cache)

        self.game_bmw = Game(
            id="lutris_bmw",
            name="Black Myth: Wukong",
            source="lutris",
            launcher="lutris",
            appid="bmw",
            executable=Path("/tmp/bmw.exe"),
        )
        self.game_cs2 = Game(
            id="steam_730",
            name="Counter-Strike 2",
            source="steam",
            launcher="steam",
            appid="730",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_default_profiles_generated(self) -> None:
        """Verify Lutris, Wine, Proton Experimental profiles are generated for Black Myth."""
        profiles = self.prof_manager.get_profiles(self.game_bmw)
        profile_names = {p.name for p in profiles}

        # Should have Primary Lutris Profile, Wine Runner, Proton Experimental
        self.assertIn("Lutris Profile", profile_names)
        self.assertIn("Wine Runner", profile_names)
        self.assertIn("Proton Experimental", profile_names)

    def test_switch_default_profile(self) -> None:
        """Verify switching default launch profile in SQLite."""
        profiles = self.prof_manager.get_profiles(self.game_bmw)
        proton_prof = [p for p in profiles if "Proton" in p.name][0]

        # Switch default to Proton Experimental
        self.assertTrue(self.prof_manager.set_default_profile(self.game_bmw.id, proton_prof.id))

        # Re-query
        updated_profiles = self.prof_manager.get_profiles(self.game_bmw)
        default_p = [p for p in updated_profiles if p.is_default][0]
        self.assertEqual(default_p.id, proton_prof.id)
        self.assertEqual(default_p.launcher, "proton")

    def test_custom_profile_creation_and_persistence(self) -> None:
        """Verify user can create a custom launch profile with environment variables."""
        custom_prof = LaunchProfile(
            id="lutris_bmw_custom_ge",
            game_id="lutris_bmw",
            name="Proton-GE Custom",
            launcher="proton",
            executable=Path("/tmp/custom.exe"),
            launch_args="-high -novid",
            env_vars={"DXVK_ASYNC": "1", "MANGOHUD": "1"},
            is_default=False,
        )
        self.prof_manager.save_profile(custom_prof)

        persisted = self.prof_manager.get_profiles(self.game_bmw)
        custom_match = [p for p in persisted if p.name == "Proton-GE Custom"][0]

        self.assertEqual(custom_match.launch_args, "-high -novid")
        self.assertEqual(custom_match.env_vars.get("MANGOHUD"), "1")

    def test_no_duplicated_provider_entries(self) -> None:
        """Profiles do not create extra game rows in the cached_games table."""
        self.prof_manager.get_profiles(self.game_bmw)
        games_in_db = self.cache.get_all_cached_games()
        # Games in library must not be duplicated by profile generation
        self.assertEqual(len([g for g in games_in_db if g.id == self.game_bmw.id]), 0)


if __name__ == "__main__":
    unittest.main()
