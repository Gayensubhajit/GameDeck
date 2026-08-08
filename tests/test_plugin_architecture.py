"""Unit tests for the plugin-architecture provider system."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gamedeck.models import Game
from gamedeck.provider_manager import (
    PROVIDER_PRIORITY,
    ProviderManager,
    _discover_provider_classes,
    sort_games_with_recents,
)
from gamedeck.providers import BaseProvider
from gamedeck.providers.filesystem import FilesystemProvider
from gamedeck.providers.heroic import HeroicProvider
from gamedeck.providers.lutris import LutrisProvider
from gamedeck.providers.native import NativeProvider
from gamedeck.providers.steam import SteamProvider


# ---------------------------------------------------------------------------
# Helper stub
# ---------------------------------------------------------------------------


class _StubProvider(BaseProvider):
    """Minimal concrete provider for testing — not part of any package."""

    name: str = "stub"
    priority: int = 99

    def enabled(self) -> bool:  # pragma: no cover
        return True

    def scan(self) -> list[Game]:  # pragma: no cover
        return []


# ---------------------------------------------------------------------------
# 1. BaseProvider interface
# ---------------------------------------------------------------------------


class TestBaseProviderInterface(unittest.TestCase):
    """Verify that BaseProvider enforces the abstract interface contract."""

    def test_cannot_instantiate_base_provider_directly(self) -> None:
        """BaseProvider must be abstract and refuse direct instantiation."""
        with self.assertRaises(TypeError):
            BaseProvider()  # type: ignore[abstract]

    def test_concrete_subclass_can_be_instantiated(self) -> None:
        """A complete concrete subclass must be instantiable without error."""
        provider = _StubProvider()
        self.assertIsInstance(provider, BaseProvider)

    def test_get_games_shim_delegates_to_scan(self) -> None:
        """The get_games() shim on BaseProvider must call scan()."""

        class _CountingProvider(BaseProvider):
            name: str = "counting"
            priority: int = 1
            call_count = 0

            def enabled(self) -> bool:
                return True

            def scan(self) -> list[Game]:
                _CountingProvider.call_count += 1
                return []

        p = _CountingProvider()
        p.get_games()
        self.assertEqual(_CountingProvider.call_count, 1)

    def test_scan_and_get_games_return_same_result(self) -> None:
        """scan() and get_games() must produce identical results."""
        steam = SteamProvider(steam_roots=[])
        self.assertEqual(steam.scan(), steam.get_games())


# ---------------------------------------------------------------------------
# 2. All built-in providers inherit BaseProvider
# ---------------------------------------------------------------------------


class TestProviderInheritance(unittest.TestCase):
    """Verify that every built-in provider is a concrete BaseProvider subclass."""

    def test_steam_inherits_base_provider(self) -> None:
        self.assertTrue(issubclass(SteamProvider, BaseProvider))

    def test_lutris_inherits_base_provider(self) -> None:
        self.assertTrue(issubclass(LutrisProvider, BaseProvider))

    def test_heroic_inherits_base_provider(self) -> None:
        self.assertTrue(issubclass(HeroicProvider, BaseProvider))

    def test_native_inherits_base_provider(self) -> None:
        self.assertTrue(issubclass(NativeProvider, BaseProvider))

    def test_filesystem_inherits_base_provider(self) -> None:
        self.assertTrue(issubclass(FilesystemProvider, BaseProvider))

    def test_provider_alias_is_base_provider(self) -> None:
        """Provider and GameProvider aliases must resolve to BaseProvider."""
        from gamedeck.providers import GameProvider, Provider

        self.assertIs(Provider, BaseProvider)
        self.assertIs(GameProvider, BaseProvider)


# ---------------------------------------------------------------------------
# 3. name and priority class attributes
# ---------------------------------------------------------------------------


class TestProviderAttributes(unittest.TestCase):
    """Verify name and priority on all five built-in providers."""

    _EXPECTED: list[tuple[type[BaseProvider], str, int]] = [
        (SteamProvider, "steam", 50),
        (HeroicProvider, "heroic", 40),
        (LutrisProvider, "lutris", 30),
        (NativeProvider, "native", 20),
        (FilesystemProvider, "filesystem", 10),
    ]

    def _make(self, cls: type[BaseProvider]) -> BaseProvider:
        """Create an instance without triggering filesystem discovery."""
        return cls.__new__(cls)

    def test_name_attributes(self) -> None:
        """Every provider instance must expose the correct name string."""
        for cls, expected_name, _ in self._EXPECTED:
            with self.subTest(cls=cls.__name__):
                inst = cls()
                self.assertEqual(inst.name, expected_name)

    def test_priority_attributes(self) -> None:
        """Every provider instance must expose the correct priority integer."""
        for cls, _, expected_priority in self._EXPECTED:
            with self.subTest(cls=cls.__name__):
                inst = cls()
                self.assertEqual(inst.priority, expected_priority)

    def test_priority_order(self) -> None:
        """Steam > Heroic > Lutris > Native > Filesystem."""
        steam_prio = SteamProvider().priority
        heroic_prio = HeroicProvider().priority
        lutris_prio = LutrisProvider().priority
        native_prio = NativeProvider().priority
        fs_prio = FilesystemProvider().priority

        self.assertGreater(steam_prio, heroic_prio)
        self.assertGreater(heroic_prio, lutris_prio)
        self.assertGreater(lutris_prio, native_prio)
        self.assertGreater(native_prio, fs_prio)

    def test_provider_priority_dict_consistent(self) -> None:
        """PROVIDER_PRIORITY dict must agree with BaseProvider subclass priorities."""
        for cls, name, expected in self._EXPECTED:
            with self.subTest(provider=name):
                self.assertEqual(PROVIDER_PRIORITY[name], expected)


# ---------------------------------------------------------------------------
# 4. enabled() method
# ---------------------------------------------------------------------------


class TestProviderEnabled(unittest.TestCase):
    """Verify that enabled() returns bool and correctly gates on prerequisites."""

    def test_enabled_returns_bool(self) -> None:
        """enabled() must always return a bool, even with no dirs present."""
        for cls in (SteamProvider, LutrisProvider, HeroicProvider, NativeProvider, FilesystemProvider):
            with self.subTest(cls=cls.__name__):
                result = cls().enabled()
                self.assertIsInstance(result, bool)

    def test_steam_enabled_when_root_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            provider = SteamProvider(steam_roots=[Path(tmpdir)])
            self.assertTrue(provider.enabled())

    def test_steam_disabled_when_no_roots(self) -> None:
        provider = SteamProvider(steam_roots=[Path("/nonexistent_steam_root_xyzzy")])
        self.assertFalse(provider.enabled())

    def test_lutris_enabled_when_config_dir_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            provider = LutrisProvider(config_dirs=[Path(tmpdir)])
            self.assertTrue(provider.enabled())

    def test_lutris_disabled_when_no_dirs(self) -> None:
        provider = LutrisProvider(config_dirs=[Path("/nonexistent_lutris_xyzzy")])
        self.assertFalse(provider.enabled())

    def test_heroic_enabled_when_root_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            provider = HeroicProvider(heroic_roots=[Path(tmpdir)])
            self.assertTrue(provider.enabled())

    def test_heroic_disabled_when_no_roots(self) -> None:
        provider = HeroicProvider(heroic_roots=[Path("/nonexistent_heroic_xyzzy")])
        self.assertFalse(provider.enabled())

    def test_native_enabled_when_app_dir_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            provider = NativeProvider(app_dirs=[Path(tmpdir)])
            self.assertTrue(provider.enabled())

    def test_native_disabled_when_no_dirs(self) -> None:
        provider = NativeProvider(app_dirs=[Path("/nonexistent_apps_xyzzy")])
        self.assertFalse(provider.enabled())

    def test_filesystem_enabled_when_dir_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            provider = FilesystemProvider(search_dirs=[Path(tmpdir)])
            self.assertTrue(provider.enabled())

    def test_filesystem_disabled_when_no_dirs(self) -> None:
        provider = FilesystemProvider(search_dirs=[Path("/nonexistent_games_xyzzy")])
        self.assertFalse(provider.enabled())


# ---------------------------------------------------------------------------
# 5. Auto-discovery
# ---------------------------------------------------------------------------


class TestProviderDiscovery(unittest.TestCase):
    """Verify that _discover_provider_classes() finds all five built-in providers."""

    def test_discovers_all_builtins(self) -> None:
        registry = _discover_provider_classes()
        expected_names = {"steam", "heroic", "lutris", "native", "filesystem"}
        self.assertTrue(
            expected_names.issubset(registry.keys()),
            f"Missing providers: {expected_names - registry.keys()}",
        )

    def test_discovered_classes_are_base_provider_subclasses(self) -> None:
        registry = _discover_provider_classes()
        for name, cls in registry.items():
            with self.subTest(provider=name):
                self.assertTrue(issubclass(cls, BaseProvider))
                self.assertIsNot(cls, BaseProvider)

    def test_discovered_classes_have_no_abstract_methods(self) -> None:
        registry = _discover_provider_classes()
        for name, cls in registry.items():
            with self.subTest(provider=name):
                abstract = getattr(cls, "__abstractmethods__", frozenset())
                self.assertFalse(abstract, f"{cls.__name__} still has abstract methods: {abstract}")

    def test_base_provider_itself_not_in_registry(self) -> None:
        registry = _discover_provider_classes()
        self.assertNotIn(BaseProvider, registry.values())


# ---------------------------------------------------------------------------
# 6. ProviderManager — disabled provider skipped
# ---------------------------------------------------------------------------


class TestProviderManagerDisabledSkip(unittest.TestCase):
    """Verify that providers whose enabled() returns False are silently skipped."""

    def test_disabled_provider_games_not_included(self) -> None:
        sentinel_game = Game(
            id="steam_999",
            name="Sentinel Game",
            source="steam",
            launcher="steam",
        )

        with (
            patch.object(SteamProvider, "enabled", return_value=False),
            patch.object(SteamProvider, "scan", return_value=[sentinel_game]) as mock_scan,
        ):
            manager = ProviderManager(enabled_providers=["steam"])
            games = manager.get_games()

        mock_scan.assert_not_called()
        self.assertNotIn(sentinel_game, games)

    def test_enabled_provider_games_included(self) -> None:
        sentinel_game = Game(
            id="steam_888",
            name="Enabled Game",
            source="steam",
            launcher="steam",
        )

        with (
            patch.object(SteamProvider, "enabled", return_value=True),
            patch.object(SteamProvider, "scan", return_value=[sentinel_game]),
        ):
            manager = ProviderManager(enabled_providers=["steam"])
            games = manager.get_games()

        self.assertIn(sentinel_game, games)


# ---------------------------------------------------------------------------
# 7. Custom provider injection
# ---------------------------------------------------------------------------


class TestCustomProviderInjection(unittest.TestCase):
    """Verify that custom_providers shadow auto-discovered providers."""

    def test_custom_callable_overrides_discovery(self) -> None:
        game = Game(id="custom_1", name="Custom Game", source="steam", launcher="steam")
        custom = lambda: [game]

        manager = ProviderManager(
            enabled_providers=["steam"],
            custom_providers={"steam": custom},
        )
        # Patch the real SteamProvider.scan so we can detect if it is called
        with patch.object(SteamProvider, "scan", return_value=[]) as mock_scan:
            games = manager.get_games()

        mock_scan.assert_not_called()
        self.assertIn(game, games)

    def test_custom_base_provider_instance_used(self) -> None:
        """A custom BaseProvider instance in custom_providers must have scan() called."""

        class _CustomSteam(BaseProvider):
            name: str = "steam"
            priority: int = 50

            def enabled(self) -> bool:
                return True

            def scan(self) -> list[Game]:
                return [
                    Game(id="custom_steam_1", name="Custom Steam", source="steam", launcher="steam")
                ]

        custom_instance = _CustomSteam()
        manager = ProviderManager(
            enabled_providers=["steam"],
            custom_providers={"steam": custom_instance},
        )
        with patch.object(SteamProvider, "scan", return_value=[]) as mock_scan:
            games = manager.get_games()

        mock_scan.assert_not_called()
        self.assertEqual(len(games), 1)
        self.assertEqual(games[0].id, "custom_steam_1")

    def test_disabled_custom_base_provider_skipped(self) -> None:
        """A custom BaseProvider instance with enabled()=False must be skipped."""

        class _DisabledCustom(BaseProvider):
            name: str = "steam"
            priority: int = 50

            def enabled(self) -> bool:
                return False

            def scan(self) -> list[Game]:  # pragma: no cover
                raise AssertionError("scan() must not be called when disabled")

        manager = ProviderManager(
            enabled_providers=["steam"],
            custom_providers={"steam": _DisabledCustom()},
        )
        games = manager.get_games()
        self.assertEqual(games, [])


# ---------------------------------------------------------------------------
# 8. Priority resolution via BaseProvider attribute
# ---------------------------------------------------------------------------


class TestPriorityResolution(unittest.TestCase):
    """Verify that _get_priority() reads the BaseProvider.priority attribute."""

    def test_priority_resolved_from_provider_attribute(self) -> None:
        manager = ProviderManager()
        self.assertEqual(manager._get_priority("steam"), 50)
        self.assertEqual(manager._get_priority("heroic"), 40)
        self.assertEqual(manager._get_priority("lutris"), 30)
        self.assertEqual(manager._get_priority("native"), 20)
        self.assertEqual(manager._get_priority("filesystem"), 10)

    def test_unknown_source_returns_zero(self) -> None:
        manager = ProviderManager()
        self.assertEqual(manager._get_priority("unknown_provider_xyz"), 0)

    def test_deduplication_uses_priority(self) -> None:
        """Steam (50) must beat Filesystem (10) in deduplication."""
        g_steam = Game(id="steam_1", name="Portal 2", source="steam", launcher="steam")
        g_fs = Game(id="fs_portal2", name="Portal 2", source="filesystem", launcher="wine")

        manager = ProviderManager()
        merged = manager.merge_and_deduplicate([g_fs, g_steam])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].source, "steam")


# ---------------------------------------------------------------------------
# 9. enabled_providers filter
# ---------------------------------------------------------------------------


class TestEnabledProvidersFilter(unittest.TestCase):
    """Verify that enabled_providers list correctly gates provider execution."""

    def test_only_named_provider_runs(self) -> None:
        """Only providers explicitly listed in enabled_providers should run."""
        lutris_game = Game(id="lutris_1", name="Witcher 3", source="lutris", launcher="lutris")
        steam_game = Game(id="steam_1", name="Witcher 3", source="steam", launcher="steam")

        with (
            patch.object(LutrisProvider, "enabled", return_value=True),
            patch.object(LutrisProvider, "scan", return_value=[lutris_game]),
            patch.object(SteamProvider, "scan", return_value=[steam_game]) as mock_steam_scan,
        ):
            manager = ProviderManager(enabled_providers=["lutris"])
            games = manager.get_games()

        # Steam must not have been invoked
        mock_steam_scan.assert_not_called()
        # Lutris game should be present
        self.assertTrue(any(g.source == "lutris" for g in games))

    def test_empty_enabled_providers_runs_nothing(self) -> None:
        """Providers not in enabled_providers list must not be invoked."""
        # Use a provider name that matches nothing in the registry
        with patch.object(SteamProvider, "scan", return_value=[]) as mock_scan:
            manager = ProviderManager(enabled_providers=["nonexistent_provider_xyz"])
            games = manager.get_games()

        mock_scan.assert_not_called()
        self.assertEqual(games, [])


# ---------------------------------------------------------------------------
# 10. scan() / get_games() backwards compatibility on all providers
# ---------------------------------------------------------------------------


class TestBackwardsCompatibility(unittest.TestCase):
    """Verify that scan() and get_games() are interchangeable on every provider."""

    def _providers_with_empty_dirs(self) -> list[BaseProvider]:
        return [
            SteamProvider(steam_roots=[]),
            LutrisProvider(config_dirs=[]),
            HeroicProvider(heroic_roots=[]),
            NativeProvider(app_dirs=[]),
            FilesystemProvider(search_dirs=[]),
        ]

    def test_get_games_is_alias_for_scan(self) -> None:
        for provider in self._providers_with_empty_dirs():
            with self.subTest(provider=type(provider).__name__):
                # Both should return an empty list when no directories configured
                self.assertEqual(provider.scan(), provider.get_games())

    def test_provider_protocol_isinstance_check(self) -> None:
        """isinstance checks against BaseProvider (aliased as Provider) still work."""
        from gamedeck.providers import Provider

        for provider in self._providers_with_empty_dirs():
            with self.subTest(provider=type(provider).__name__):
                self.assertIsInstance(provider, Provider)


if __name__ == "__main__":
    unittest.main()
