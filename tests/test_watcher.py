"""Unit tests for the FileSystemWatcher and WatcherManager game library change detection."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from gamedeck.models import Game
from gamedeck.scanner import Scanner
from gamedeck.watcher import FileSystemWatcher, WatchEvent, WatcherManager


class TestFileSystemWatcher(unittest.TestCase):
    """Test standard-library filesystem watcher change detection without external dependencies."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_detect_file_creation(self) -> None:
        """Verify watcher detects newly created manifest/yaml files."""
        watcher = FileSystemWatcher(watch_paths=[self.root], poll_interval=0.05)
        initial_events = watcher.poll_once()
        self.assertEqual(len(initial_events), 0)

        # Create a new manifest file
        new_file = self.root / "appmanifest_12345.acf"
        new_file.write_text('"AppState" { "appid" "12345" }', encoding="utf-8")

        events = watcher.poll_once()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].path, new_file)
        self.assertEqual(events[0].event_type, "created")

    def test_detect_file_modification(self) -> None:
        """Verify watcher detects file modifications."""
        yaml_file = self.root / "game.yml"
        yaml_file.write_text("name: Old Title\n", encoding="utf-8")

        watcher = FileSystemWatcher(watch_paths=[self.root], poll_interval=0.05)
        watcher.poll_once()

        # Modify the file with a short sleep to ensure timestamp differs
        time.sleep(0.02)
        yaml_file.write_text("name: New Title\n", encoding="utf-8")

        events = watcher.poll_once()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].path, yaml_file)
        self.assertEqual(events[0].event_type, "modified")

    def test_detect_file_deletion(self) -> None:
        """Verify watcher detects deleted files."""
        desktop_file = self.root / "game.desktop"
        desktop_file.write_text("[Desktop Entry]\nName=Game\n", encoding="utf-8")

        watcher = FileSystemWatcher(watch_paths=[self.root], poll_interval=0.05)
        watcher.poll_once()

        desktop_file.unlink()

        events = watcher.poll_once()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].path, desktop_file)
        self.assertEqual(events[0].event_type, "deleted")

    def test_start_and_stop_lifecycle(self) -> None:
        """Verify watcher start and stop lifecycle runs background thread cleanly."""
        watcher = FileSystemWatcher(watch_paths=[self.root], poll_interval=0.05)
        watcher.start()
        self.assertIsNotNone(watcher._thread)
        self.assertTrue(watcher._thread.is_alive())

        watcher.stop()
        self.assertIsNone(watcher._thread)


class TestWatcherManager(unittest.TestCase):
    """Test WatcherManager coordination with Scanner and LibraryCache."""

    def test_trigger_rescan_on_change(self) -> None:
        """Verify WatcherManager triggers scanner.scan() on change without restarting."""
        mock_scanner = MagicMock()
        mock_scanner.scan.return_value = [
            Game(id="steam_10", name="Counter-Strike", source="steam", launcher="steam")
        ]

        manager = WatcherManager(scanner=mock_scanner)
        results = manager.trigger_rescan()

        mock_scanner.scan.assert_called_once()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "Counter-Strike")


if __name__ == "__main__":
    unittest.main()
