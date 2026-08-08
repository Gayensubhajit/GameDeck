"""Unit tests for the plugin-architecture launcher system."""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from gamedeck.launchers import (
    BaseLauncher,
    HeroicLauncher,
    Launcher,
    LauncherManager,
    LutrisLauncher,
    NativeLauncher,
    SteamLauncher,
    WineLauncher,
    _discover_launcher_classes,
    get_launcher,
    launch,
)
from gamedeck.models import Game
from gamedeck.providers import BaseProvider
from gamedeck.providers.filesystem import FilesystemProvider
from gamedeck.providers.heroic import HeroicProvider
from gamedeck.providers.lutris import LutrisProvider
from gamedeck.providers.native import NativeProvider
from gamedeck.providers.steam import SteamProvider


# ---------------------------------------------------------------------------
# Helper stub
# ---------------------------------------------------------------------------


class _StubLauncher(BaseLauncher):
    """Minimal concrete launcher for testing — not part of any package."""

    name: str = "stub"
    aliases: tuple[str, ...] = ("stub_alias",)

    def launch(
        self,
        game: Game,
        extra_args: list[str] | None = None,
        **kwargs: object,
    ) -> subprocess.Popen[object]:  # pragma: no cover
        raise NotImplementedError("stub")


def _make_game(launcher: str = "steam") -> Game:
    return Game(id=f"{launcher}_1", name="Test Game", source=launcher, launcher=launcher)


# ---------------------------------------------------------------------------
# 1. BaseLauncher interface
# ---------------------------------------------------------------------------


class TestBaseLauncherInterface(unittest.TestCase):
    """Verify BaseLauncher enforces the abstract interface contract."""

    def test_cannot_instantiate_base_launcher_directly(self) -> None:
        """BaseLauncher must be abstract and refuse direct instantiation."""
        with self.assertRaises(TypeError):
            BaseLauncher()  # type: ignore[abstract]

    def test_concrete_subclass_can_be_instantiated(self) -> None:
        """A complete concrete subclass must be instantiable without error."""
        launcher = _StubLauncher()
        self.assertIsInstance(launcher, BaseLauncher)

    def test_launcher_alias_is_base_launcher(self) -> None:
        """The module-level 'Launcher' alias must resolve to BaseLauncher."""
        self.assertIs(Launcher, BaseLauncher)


# ---------------------------------------------------------------------------
# 2. All built-in launchers inherit BaseLauncher
# ---------------------------------------------------------------------------


class TestLauncherInheritance(unittest.TestCase):
    """Verify that every built-in launcher is a concrete BaseLauncher subclass."""

    def test_steam_inherits_base_launcher(self) -> None:
        self.assertTrue(issubclass(SteamLauncher, BaseLauncher))

    def test_heroic_inherits_base_launcher(self) -> None:
        self.assertTrue(issubclass(HeroicLauncher, BaseLauncher))

    def test_lutris_inherits_base_launcher(self) -> None:
        self.assertTrue(issubclass(LutrisLauncher, BaseLauncher))

    def test_native_inherits_base_launcher(self) -> None:
        self.assertTrue(issubclass(NativeLauncher, BaseLauncher))

    def test_wine_inherits_base_launcher(self) -> None:
        self.assertTrue(issubclass(WineLauncher, BaseLauncher))

    def test_all_built_in_launchers_are_concrete(self) -> None:
        """No built-in launcher may retain abstract methods."""
        for cls in (SteamLauncher, HeroicLauncher, LutrisLauncher, NativeLauncher, WineLauncher):
            with self.subTest(cls=cls.__name__):
                abstract = getattr(cls, "__abstractmethods__", frozenset())
                self.assertFalse(abstract, f"{cls.__name__} still has abstract methods: {abstract}")


# ---------------------------------------------------------------------------
# 3. name and aliases class attributes
# ---------------------------------------------------------------------------


class TestLauncherAttributes(unittest.TestCase):
    """Verify name and aliases on all five built-in launchers."""

    _EXPECTED: list[tuple[type[BaseLauncher], str, tuple[str, ...]]] = [
        (SteamLauncher, "steam", ()),
        (HeroicLauncher, "heroic", ()),
        (LutrisLauncher, "lutris", ()),
        (NativeLauncher, "native", ("linux",)),
        (WineLauncher, "wine", ("proton", "bottles")),
    ]

    def test_name_attributes(self) -> None:
        """Every launcher instance must expose the correct name string."""
        for cls, expected_name, _ in self._EXPECTED:
            with self.subTest(cls=cls.__name__):
                self.assertEqual(cls().name, expected_name)

    def test_aliases_attributes(self) -> None:
        """Every launcher instance must expose the correct aliases tuple."""
        for cls, _, expected_aliases in self._EXPECTED:
            with self.subTest(cls=cls.__name__):
                self.assertEqual(cls().aliases, expected_aliases)

    def test_wine_launcher_aliases_cover_proton_and_bottles(self) -> None:
        """WineLauncher aliases must include both 'proton' and 'bottles'."""
        wine = WineLauncher()
        self.assertIn("proton", wine.aliases)
        self.assertIn("bottles", wine.aliases)

    def test_native_launcher_alias_covers_linux(self) -> None:
        """NativeLauncher aliases must include 'linux'."""
        native = NativeLauncher()
        self.assertIn("linux", native.aliases)


# ---------------------------------------------------------------------------
# 4. Auto-discovery
# ---------------------------------------------------------------------------


class TestLauncherDiscovery(unittest.TestCase):
    """Verify that _discover_launcher_classes() finds all five built-in launchers."""

    def test_discovers_all_builtin_primary_names(self) -> None:
        registry = _discover_launcher_classes()
        expected = {"steam", "heroic", "lutris", "native", "wine"}
        self.assertTrue(
            expected.issubset(registry.keys()),
            f"Missing launchers: {expected - registry.keys()}",
        )

    def test_aliases_registered_in_registry(self) -> None:
        """Alias keys must resolve to the correct launcher class."""
        registry = _discover_launcher_classes()
        self.assertIn("proton", registry)
        self.assertIn("bottles", registry)
        self.assertIn("linux", registry)
        self.assertIs(registry["proton"], WineLauncher)
        self.assertIs(registry["bottles"], WineLauncher)
        self.assertIs(registry["linux"], NativeLauncher)

    def test_discovered_classes_are_base_launcher_subclasses(self) -> None:
        registry = _discover_launcher_classes()
        for key, cls in registry.items():
            with self.subTest(key=key):
                self.assertTrue(issubclass(cls, BaseLauncher))
                self.assertIsNot(cls, BaseLauncher)

    def test_base_launcher_not_in_registry(self) -> None:
        registry = _discover_launcher_classes()
        self.assertNotIn(BaseLauncher, registry.values())

    def test_discovered_classes_have_no_abstract_methods(self) -> None:
        registry = _discover_launcher_classes()
        for key, cls in registry.items():
            with self.subTest(key=key):
                abstract = getattr(cls, "__abstractmethods__", frozenset())
                self.assertFalse(abstract)


# ---------------------------------------------------------------------------
# 5. LauncherManager.get_launcher()
# ---------------------------------------------------------------------------


class TestLauncherManagerGetLauncher(unittest.TestCase):
    """Verify LauncherManager resolves launcher types correctly."""

    def setUp(self) -> None:
        self.manager = LauncherManager()

    def test_get_steam_launcher(self) -> None:
        self.assertIsInstance(self.manager.get_launcher("steam"), SteamLauncher)

    def test_get_heroic_launcher(self) -> None:
        self.assertIsInstance(self.manager.get_launcher("heroic"), HeroicLauncher)

    def test_get_lutris_launcher(self) -> None:
        self.assertIsInstance(self.manager.get_launcher("lutris"), LutrisLauncher)

    def test_get_native_launcher(self) -> None:
        self.assertIsInstance(self.manager.get_launcher("native"), NativeLauncher)

    def test_get_wine_launcher(self) -> None:
        self.assertIsInstance(self.manager.get_launcher("wine"), WineLauncher)

    def test_alias_proton_resolves_to_wine(self) -> None:
        self.assertIsInstance(self.manager.get_launcher("proton"), WineLauncher)

    def test_alias_bottles_resolves_to_wine(self) -> None:
        self.assertIsInstance(self.manager.get_launcher("bottles"), WineLauncher)

    def test_alias_linux_resolves_to_native(self) -> None:
        self.assertIsInstance(self.manager.get_launcher("linux"), NativeLauncher)

    def test_case_insensitive_resolution(self) -> None:
        """Launcher type lookup must be case-insensitive."""
        self.assertIsInstance(self.manager.get_launcher("STEAM"), SteamLauncher)
        self.assertIsInstance(self.manager.get_launcher("Heroic"), HeroicLauncher)

    def test_unknown_launcher_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            self.manager.get_launcher("nonexistent_launcher_xyz")

    def test_returns_base_launcher_instance(self) -> None:
        """All resolved launchers must be BaseLauncher instances."""
        for name in ("steam", "heroic", "lutris", "native", "wine", "proton", "bottles", "linux"):
            with self.subTest(name=name):
                self.assertIsInstance(self.manager.get_launcher(name), BaseLauncher)


# ---------------------------------------------------------------------------
# 6. Module-level shim functions
# ---------------------------------------------------------------------------


class TestModuleLevelShims(unittest.TestCase):
    """Verify module-level get_launcher() and launch() delegate correctly."""

    def test_module_get_launcher_steam(self) -> None:
        self.assertIsInstance(get_launcher("steam"), SteamLauncher)

    def test_module_get_launcher_proton_alias(self) -> None:
        self.assertIsInstance(get_launcher("proton"), WineLauncher)

    def test_module_get_launcher_unknown_raises(self) -> None:
        with self.assertRaises(ValueError):
            get_launcher("unknown_xyz")

    @patch("shutil.which")
    @patch("subprocess.Popen")
    def test_module_launch_dispatches_to_correct_launcher(
        self, mock_popen: MagicMock, mock_which: MagicMock
    ) -> None:
        """launch() at module level must call the correct launcher's launch()."""
        mock_which.return_value = "/usr/bin/steam"
        mock_popen.return_value = MagicMock()
        game = _make_game("steam")
        game.appid = "730"
        result = launch(game)
        mock_popen.assert_called_once()
        self.assertIsNotNone(result)


# ---------------------------------------------------------------------------
# 7. Launchers must never scan
# ---------------------------------------------------------------------------


class TestLaunchersNeverScan(unittest.TestCase):
    """Verify that no launcher class exposes game-scanning logic."""

    _LAUNCHER_CLASSES = [
        SteamLauncher, HeroicLauncher, LutrisLauncher, NativeLauncher, WineLauncher,
    ]

    def test_no_launcher_has_scan_method(self) -> None:
        for cls in self._LAUNCHER_CLASSES:
            with self.subTest(cls=cls.__name__):
                self.assertFalse(
                    hasattr(cls, "scan"),
                    f"{cls.__name__} must not expose scan()",
                )

    def test_no_launcher_has_get_games_method(self) -> None:
        for cls in self._LAUNCHER_CLASSES:
            with self.subTest(cls=cls.__name__):
                self.assertFalse(
                    hasattr(cls, "get_games"),
                    f"{cls.__name__} must not expose get_games()",
                )

    def test_no_launcher_has_find_method(self) -> None:
        """No launcher should expose methods starting with 'find_' (game scanning)."""
        for cls in self._LAUNCHER_CLASSES:
            with self.subTest(cls=cls.__name__):
                scanning_methods = [
                    m for m in dir(cls)
                    if m.startswith("find_") and callable(getattr(cls, m, None))
                ]
                self.assertFalse(
                    scanning_methods,
                    f"{cls.__name__} has scanning methods: {scanning_methods}",
                )


# ---------------------------------------------------------------------------
# 8. Providers must never launch
# ---------------------------------------------------------------------------


class TestProvidersNeverLaunch(unittest.TestCase):
    """Verify that no provider class exposes game execution logic."""

    _PROVIDER_CLASSES = [
        SteamProvider, HeroicProvider, LutrisProvider, NativeProvider, FilesystemProvider,
    ]

    def test_no_provider_has_launch_method(self) -> None:
        for cls in self._PROVIDER_CLASSES:
            with self.subTest(cls=cls.__name__):
                self.assertFalse(
                    hasattr(cls, "launch"),
                    f"{cls.__name__} must not expose launch()",
                )

    def test_no_provider_has_execute_method(self) -> None:
        for cls in self._PROVIDER_CLASSES:
            with self.subTest(cls=cls.__name__):
                self.assertFalse(
                    hasattr(cls, "execute"),
                    f"{cls.__name__} must not expose execute()",
                )

    def test_no_provider_has_run_method(self) -> None:
        for cls in self._PROVIDER_CLASSES:
            with self.subTest(cls=cls.__name__):
                self.assertFalse(
                    hasattr(cls, "run"),
                    f"{cls.__name__} must not expose run()",
                )


# ---------------------------------------------------------------------------
# 9. Correct launcher dispatched for each game.launcher value
# ---------------------------------------------------------------------------


class TestLaunchDispatch(unittest.TestCase):
    """Verify that LauncherManager routes each game.launcher to the right backend."""

    @patch("shutil.which")
    @patch("subprocess.Popen")
    def test_steam_game_uses_steam_launcher(
        self, mock_popen: MagicMock, mock_which: MagicMock
    ) -> None:
        mock_which.return_value = "/usr/bin/steam"
        mock_popen.return_value = MagicMock()
        game = Game(id="steam_730", name="CS2", source="steam", launcher="steam", appid="730")
        manager = LauncherManager()
        manager.launch(game)
        cmd = mock_popen.call_args[0][0]
        self.assertTrue(any("steam" in str(c).lower() for c in cmd))

    @patch("shutil.which")
    @patch("subprocess.Popen")
    def test_heroic_game_uses_heroic_launcher(
        self, mock_popen: MagicMock, mock_which: MagicMock
    ) -> None:
        mock_which.side_effect = lambda cmd: "/usr/bin/heroic" if cmd == "heroic" else None
        mock_popen.return_value = MagicMock()
        game = Game(id="heroic_Sugar", name="GTA V", source="heroic", launcher="heroic", appid="Sugar")
        manager = LauncherManager()
        manager.launch(game)
        cmd = mock_popen.call_args[0][0]
        self.assertIn("/usr/bin/heroic", cmd)

    @patch("shutil.which")
    @patch("subprocess.Popen")
    def test_lutris_game_uses_lutris_launcher(
        self, mock_popen: MagicMock, mock_which: MagicMock
    ) -> None:
        mock_which.side_effect = lambda cmd: "/usr/bin/lutris" if cmd == "lutris" else None
        mock_popen.return_value = MagicMock()
        game = Game(
            id="lutris_wukong",
            name="Black Myth Wukong",
            source="lutris",
            launcher="lutris",
            appid="black-myth-wukong",
        )
        manager = LauncherManager()
        manager.launch(game)
        cmd = mock_popen.call_args[0][0]
        self.assertIn("/usr/bin/lutris", cmd)

    @patch("shutil.which")
    @patch("subprocess.Popen")
    def test_proton_alias_uses_wine_launcher(
        self, mock_popen: MagicMock, mock_which: MagicMock
    ) -> None:
        """A game with launcher='proton' must be executed by WineLauncher."""
        exe = Path(__file__)  # guaranteed to exist
        mock_which.side_effect = lambda cmd: "/usr/bin/wine" if cmd == "wine" else None
        mock_popen.return_value = MagicMock()
        game = Game(
            id="fs_proton_game",
            name="Proton Game",
            source="filesystem",
            launcher="proton",
            executable=exe,
        )
        manager = LauncherManager()
        resolved = manager.get_launcher("proton")
        self.assertIsInstance(resolved, WineLauncher)

    @patch("shutil.which")
    @patch("subprocess.Popen")
    def test_bottles_alias_uses_wine_launcher(
        self, mock_popen: MagicMock, mock_which: MagicMock
    ) -> None:
        """A game with launcher='bottles' must be executed by WineLauncher."""
        manager = LauncherManager()
        resolved = manager.get_launcher("bottles")
        self.assertIsInstance(resolved, WineLauncher)

    def test_linux_alias_uses_native_launcher(self) -> None:
        """A game with launcher='linux' must be executed by NativeLauncher."""
        manager = LauncherManager()
        resolved = manager.get_launcher("linux")
        self.assertIsInstance(resolved, NativeLauncher)

    def test_unknown_launcher_raises_value_error(self) -> None:
        manager = LauncherManager()
        game = _make_game("nonexistent_xyz")
        with self.assertRaises(ValueError):
            manager.launch(game)


# ---------------------------------------------------------------------------
# 10. Game objects reference launcher names only (no embedded logic)
# ---------------------------------------------------------------------------


class TestGameLauncherNameOnly(unittest.TestCase):
    """Verify Game.launcher is a plain string name — not an object or callable."""

    def test_game_launcher_is_string(self) -> None:
        for launcher_name in ("steam", "heroic", "lutris", "native", "wine", "proton"):
            game = _make_game(launcher_name)
            with self.subTest(launcher=launcher_name):
                self.assertIsInstance(game.launcher, str)
                self.assertEqual(game.launcher, launcher_name)

    def test_game_launcher_not_callable(self) -> None:
        game = _make_game("steam")
        self.assertFalse(callable(game.launcher))


if __name__ == "__main__":
    unittest.main()
