"""Unit tests for the dynamic Game Actions system."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from gamedeck.actions import (
    ActionRegistry,
    BaseActionProvider,
    FilesystemActionProvider,
    GameAction,
    HeroicActionProvider,
    LutrisActionProvider,
    NativeActionProvider,
    SteamActionProvider,
    execute_action,
    get_actions_for_game,
)
from gamedeck.models import Game


class TestGameActionsSystem(unittest.TestCase):
    """Test dynamic game action querying, extensibility, and provider action dispatch."""

    def test_steam_actions(self) -> None:
        """Verify Steam actions: Play, Open Steam Page, Browse Files."""
        game = Game(
            id="steam_730",
            name="Counter-Strike 2",
            source="steam",
            launcher="steam",
            executable=Path("/home/user/.steam/steam/steamapps/common/Counter-Strike Global Offensive/cs2"),
            appid="730",
        )

        actions = get_actions_for_game(game)
        action_ids = [a.id for a in actions]

        self.assertIn("play", action_ids)
        self.assertIn("open_steam_page", action_ids)
        self.assertIn("browse_files", action_ids)

    def test_lutris_actions(self) -> None:
        """Verify Lutris actions: Play, Configure, Browse Files."""
        with patch("shutil.which", return_value="/usr/bin/lutris"):
            game = Game(
                id="lutris_bmw",
                name="Black Myth: Wukong",
                source="lutris",
                launcher="lutris",
                executable=Path("/mnt/windows/Games/BMW/b1.exe"),
                appid="black-myth-wukong",
            )

            actions = get_actions_for_game(game)
            action_ids = [a.id for a in actions]

            self.assertIn("play", action_ids)
            self.assertIn("configure", action_ids)
            self.assertIn("browse_files", action_ids)

    def test_heroic_actions(self) -> None:
        """Verify Heroic actions: Play, Browse Files, Open Heroic."""
        with patch("shutil.which", return_value="/usr/bin/heroic"):
            game = Game(
                id="heroic_cyberpunk",
                name="Cyberpunk 2077",
                source="heroic",
                launcher="heroic",
                executable=Path("/home/user/Games/Heroic/Cyberpunk/bin/Cyberpunk2077.exe"),
                appid="cyberpunk",
            )

            actions = get_actions_for_game(game)
            action_ids = [a.id for a in actions]

            self.assertIn("play", action_ids)
            self.assertIn("browse_files", action_ids)
            self.assertIn("open_heroic", action_ids)

    def test_native_actions(self) -> None:
        """Verify Native Linux actions: Launch, Open Folder."""
        game = Game(
            id="native_kblackbox",
            name="KBlackBox",
            source="native",
            launcher="native",
            executable=Path("/usr/bin/kblackbox"),
            appid="org.kde.kblackbox",
        )

        actions = get_actions_for_game(game)
        action_ids = [a.id for a in actions]

        self.assertIn("launch", action_ids)
        self.assertIn("browse_files", action_ids)

    def test_filesystem_actions(self) -> None:
        """Verify Filesystem/Wine actions: Play, Open Folder."""
        game = Game(
            id="fs_game",
            name="Standalone Game",
            source="filesystem",
            launcher="wine",
            executable=Path("/mnt/storage/Games/Indie/game.exe"),
        )

        actions = get_actions_for_game(game)
        action_ids = [a.id for a in actions]

        self.assertIn("play", action_ids)
        self.assertIn("open_folder", action_ids)

    def test_custom_extensibility(self) -> None:
        """Verify custom action provider registration and dynamic querying."""

        class ModdingActionProvider(BaseActionProvider):
            sources = ("steam", "lutris")

            def get_actions(self, game: Game) -> list[GameAction]:
                return [
                    GameAction(
                        id="open_mods",
                        label="Open Mods Folder",
                        handler=lambda g: "opened_mods",
                        icon="🧩",
                    )
                ]

        registry = ActionRegistry.default()
        registry.register(ModdingActionProvider())

        game = Game(
            id="steam_730",
            name="Counter-Strike 2",
            source="steam",
            launcher="steam",
        )

        actions = registry.get_actions(game)
        action_ids = [a.id for a in actions]
        self.assertIn("open_mods", action_ids)

    def test_execute_action_helper(self) -> None:
        """Verify execute_action triggers handler directly."""
        mock_handler = MagicMock(return_value="executed_ok")
        action = GameAction(
            id="custom_action",
            label="Custom",
            handler=mock_handler,
        )

        game = Game(id="g1", name="Game", source="native", launcher="native")
        res = action.execute(game)
        self.assertEqual(res, "executed_ok")
        mock_handler.assert_called_once_with(game)


if __name__ == "__main__":
    unittest.main()
