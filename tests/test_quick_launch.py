"""Unit tests for Quick Launch configuration and Rofi UI interaction model."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from gamedeck.config.settings import Settings, UIConfig
from gamedeck.models import Game
from gamedeck.ui.rofi import RofiUI


class TestQuickLaunchInteractionModel(unittest.TestCase):
    """Test quick_launch config toggle and action menu routing."""

    def setUp(self) -> None:
        self.game = Game(id="steam_730", name="Counter-Strike 2", source="steam", launcher="steam")
        self.games = [self.game]

    def test_ui_config_defaults(self) -> None:
        """Verify ui.quick_launch defaults to True (Enter launches immediately, Alt+Return opens action menu)."""
        cfg = UIConfig()
        self.assertTrue(cfg.quick_launch)
        self.assertEqual(cfg.secondary_action_key, "Alt+Return")

    def test_settings_from_dict_quick_launch(self) -> None:
        """Verify quick_launch is parsed correctly from settings dictionary."""
        data = {"ui": {"quick_launch": True, "secondary_action_key": "Super+Return"}}
        settings = Settings.from_dict(data)
        self.assertTrue(settings.ui.quick_launch)
        self.assertEqual(settings.ui.secondary_action_key, "Super+Return")

    @patch.object(RofiUI, "select")
    @patch.object(RofiUI, "select_game_action")
    def test_default_mode_enter_opens_action_menu(self, mock_action: MagicMock, mock_select: MagicMock) -> None:
        """When quick_launch is False (default), Enter on a game opens the action menu."""
        ui = RofiUI(quick_launch=False)
        mock_select.return_value = self.game
        mock_action.return_value = ("launch", None)

        game, act = ui.select_with_action(self.games)

        self.assertEqual(game, self.game)
        mock_action.assert_called_once_with(self.game)

    @patch.object(RofiUI, "select")
    @patch.object(RofiUI, "select_game_action")
    def test_default_mode_secondary_key_launches_immediately(self, mock_action: MagicMock, mock_select: MagicMock) -> None:
        """When quick_launch is False, pressing secondary key launches immediately."""
        ui = RofiUI(quick_launch=False)
        mock_select.return_value = (self.game, "SECONDARY_KEY")

        game, act = ui.select_with_action(self.games)

        self.assertEqual(game, self.game)
        self.assertEqual(act, "launch")
        mock_action.assert_not_called()

    @patch.object(RofiUI, "select")
    @patch.object(RofiUI, "select_game_action")
    def test_quick_launch_mode_enter_launches_immediately(self, mock_action: MagicMock, mock_select: MagicMock) -> None:
        """When quick_launch is True, Enter on a game launches immediately."""
        ui = RofiUI(quick_launch=True)
        mock_select.return_value = self.game

        game, act = ui.select_with_action(self.games)

        self.assertEqual(game, self.game)
        self.assertEqual(act, "launch")
        mock_action.assert_not_called()

    @patch.object(RofiUI, "select")
    @patch.object(RofiUI, "select_game_action")
    def test_quick_launch_mode_secondary_key_opens_action_menu(self, mock_action: MagicMock, mock_select: MagicMock) -> None:
        """When quick_launch is True, secondary key opens the action menu."""
        ui = RofiUI(quick_launch=True)
        mock_select.return_value = (self.game, "SECONDARY_KEY")
        mock_action.return_value = ("toggle_favorite", None)

        game, act = ui.select_with_action(self.games)

        self.assertEqual(game, self.game)
        mock_action.assert_called_once_with(self.game)


if __name__ == "__main__":
    unittest.main()
