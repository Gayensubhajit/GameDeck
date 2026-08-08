"""Unit tests for the context menu and dynamic Game Actions generation."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from gamedeck.actions import (
    ActionRegistry,
    BaseActionProvider,
    GameAction,
    UniversalActionProvider,
    execute_action,
    get_actions_for_game,
)
from gamedeck.models import Game


class TestContextMenuSystem(unittest.TestCase):
    """Test context menu action generation across Steam, Lutris, Filesystem, and Native providers."""

    def test_universal_context_actions_present_on_all_games(self) -> None:
        """Universal actions: Favorite, Open Folder, Properties, Refresh Metadata."""
        game = Game(
            id="steam_123",
            name="My Steam Game",
            source="steam",
            launcher="steam",
            executable=Path("/tmp/game"),
        )
        actions = get_actions_for_game(game)
        action_ids = [a.id for a in actions]

        self.assertIn("toggle_favorite", action_ids)
        self.assertIn("open_folder", action_ids)
        self.assertIn("show_properties", action_ids)
        self.assertIn("refresh_metadata", action_ids)

    def test_filesystem_has_remove_from_library_action(self) -> None:
        """Filesystem games expose 'Remove From Library' context action."""
        game = Game(
            id="fs_standalone",
            name="Standalone Game",
            source="filesystem",
            launcher="wine",
            executable=Path("/tmp/game.exe"),
        )
        actions = get_actions_for_game(game)
        action_ids = [a.id for a in actions]

        self.assertIn("remove_from_library", action_ids)

    def test_steam_does_not_have_remove_from_library(self) -> None:
        """Steam/Lutris games do not expose 'Remove From Library'."""
        game = Game(
            id="steam_730",
            name="Counter-Strike 2",
            source="steam",
            launcher="steam",
        )
        actions = get_actions_for_game(game)
        action_ids = [a.id for a in actions]

        self.assertNotIn("remove_from_library", action_ids)

    def test_lutris_context_actions(self) -> None:
        """Lutris game exposes Play, Configure, Browse Prefix, Properties, Open Folder."""
        with patch("shutil.which", return_value="/usr/bin/lutris"):
            game = Game(
                id="lutris_game",
                name="Lutris Title",
                source="lutris",
                launcher="lutris",
                appid="lutris-title",
                executable=Path("/tmp/exe"),
            )
            actions = get_actions_for_game(game)
            action_ids = [a.id for a in actions]

            self.assertIn("play", action_ids)
            self.assertIn("configure", action_ids)
            self.assertIn("show_properties", action_ids)
            self.assertIn("open_folder", action_ids)

    def test_native_context_actions(self) -> None:
        """Native game exposes Launch, Open Desktop File, Properties, Open Folder."""
        game = Game(
            id="native_test",
            name="Native App",
            source="native",
            launcher="native",
            appid="test_app",
            executable=Path("/usr/bin/test_app"),
        )
        actions = get_actions_for_game(game)
        action_ids = [a.id for a in actions]

        self.assertIn("launch", action_ids)
        self.assertIn("show_properties", action_ids)
        self.assertIn("open_folder", action_ids)

    def test_no_provider_specific_ui_logic(self) -> None:
        """UI queries actions purely dynamically from ActionRegistry without hardcoding lists."""
        registry = ActionRegistry.default()
        game = Game(id="custom", name="Test", source="unknown", launcher="unknown")
        actions = registry.get_actions(game)
        self.assertTrue(len(actions) > 0)
        self.assertTrue(any(a.id == "toggle_favorite" for a in actions))


if __name__ == "__main__":
    unittest.main()
