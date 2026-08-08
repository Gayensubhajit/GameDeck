"""Cross-platform, standard-library filesystem watching service for game libraries and configs."""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

__all__ = [
    "FileSystemWatcher",
    "WatchEvent",
    "WatcherManager",
]

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class WatchEvent:
    """An event representing a modification, creation, or deletion in a watched directory."""

    path: Path
    event_type: str  # 'modified', 'created', 'deleted'
    timestamp: float = field(default_factory=time.time)


@dataclass(slots=True)
class FileSystemWatcher:
    """Standard-library filesystem watcher polling modification times and directory listings.

    Isolates file watching without requiring external third-party packages (like watchdog).
    Uses a background worker thread with debounced notifications to detect changes in:
    - Steam library manifests (`appmanifest_*.acf`, `libraryfolders.vdf`)
    - Lutris game YAML configurations (`*.yml`, `*.yaml`)
    - Heroic store configurations (`installed.json`, `legendaryConfig`)
    - Native Linux desktop files (`*.desktop`)
    - Local filesystem game folders and executables

    Attributes:
        watch_paths: Set of directory or file paths to watch.
        callback: Function invoked when changes are detected: `callback(events)`.
        poll_interval: Frequency of polling checks in seconds (default 1.0s).
        debounce_interval: Debounce delay in seconds before triggering callback (default 0.5s).
    """

    watch_paths: list[Path] = field(default_factory=list)
    callback: Callable[[list[WatchEvent]], None] | None = None
    poll_interval: float = 1.0
    debounce_interval: float = 0.5

    _snapshot: dict[Path, tuple[float, int]] = field(default_factory=dict, init=False, repr=False)
    _stop_event: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        """Initialize initial snapshot of watch paths."""
        self._snapshot = self._take_snapshot()

    def start(self) -> None:
        """Start the background watcher thread."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._snapshot = self._take_snapshot()
            self._thread = threading.Thread(
                target=self._watch_loop,
                name="GameDeckFSWatcher",
                daemon=True,
            )
            self._thread.start()
            logger.debug("FileSystemWatcher started watching %d paths", len(self.watch_paths))

    def stop(self) -> None:
        """Stop the background watcher thread gracefully."""
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None
        logger.debug("FileSystemWatcher stopped")

    def add_path(self, path: Path | str) -> None:
        """Add a new path to the watch list."""
        p = Path(path).expanduser().resolve()
        with self._lock:
            if p not in self.watch_paths:
                self.watch_paths.append(p)
                self._update_snapshot_for_path(p)

    def remove_path(self, path: Path | str) -> None:
        """Remove a path from the watch list."""
        p = Path(path).expanduser().resolve()
        with self._lock:
            if p in self.watch_paths:
                self.watch_paths.remove(p)

    def poll_once(self) -> list[WatchEvent]:
        """Perform a single synchronous check and return any detected events."""
        with self._lock:
            current = self._take_snapshot()
            events = self._diff_snapshots(self._snapshot, current)
            self._snapshot = current
            return events

    # ------------------------------------------------------------------
    # Internal Watch Loop
    # ------------------------------------------------------------------

    def _watch_loop(self) -> None:
        """Worker thread loop polling filesystem snapshots periodically."""
        pending_events: list[WatchEvent] = []
        last_change_time: float = 0.0

        while not self._stop_event.is_set():
            time.sleep(self.poll_interval)
            if self._stop_event.is_set():
                break

            events = self.poll_once()
            if events:
                pending_events.extend(events)
                last_change_time = time.time()

            # Debounce: trigger callback once changes settle
            if pending_events and (time.time() - last_change_time) >= self.debounce_interval:
                if self.callback is not None:
                    try:
                        self.callback(list(pending_events))
                    except Exception as err:
                        logger.error("Watcher callback error: %s", err)
                pending_events.clear()

    def _take_snapshot(self) -> dict[Path, tuple[float, int]]:
        """Snapshot file and directory modification times and sizes."""
        snapshot: dict[Path, tuple[float, int]] = {}
        for root in self.watch_paths:
            if not root.exists():
                continue

            try:
                stat = root.stat()
                snapshot[root] = (stat.st_mtime_ns, stat.st_size)
            except OSError:
                continue

            if root.is_dir():
                try:
                    for child in root.iterdir():
                        if child.name.startswith("."):
                            continue
                        try:
                            cstat = child.stat()
                            snapshot[child] = (cstat.st_mtime_ns, cstat.st_size)
                        except OSError:
                            continue
                except OSError:
                    continue

        return snapshot

    def _update_snapshot_for_path(self, path: Path) -> None:
        """Update snapshot entries for a newly added path."""
        if not path.exists():
            return
        try:
            stat = path.stat()
            self._snapshot[path] = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            pass

    def _diff_snapshots(
        self,
        old: dict[Path, tuple[float, int]],
        new: dict[Path, tuple[float, int]],
    ) -> list[WatchEvent]:
        """Compute differences between two filesystem snapshots."""
        events: list[WatchEvent] = []

        # Check created / modified
        for path, (mtime, size) in new.items():
            if path in self.watch_paths and path.is_dir():
                # Directory roots change mtime when children are created/deleted; avoid emitting root events
                continue

            if path not in old:
                events.append(WatchEvent(path=path, event_type="created"))
            elif old[path] != (mtime, size):
                events.append(WatchEvent(path=path, event_type="modified"))

        # Check deleted
        for path in old:
            if path in self.watch_paths and path.is_dir():
                continue
            if path not in new:
                events.append(WatchEvent(path=path, event_type="deleted"))

        return events


@dataclass(slots=True)
class WatcherManager:
    """Manages watchers across all game library providers and auto-updates the LibraryCache.

    Watches:
    - Steam library manifest folders and `libraryfolders.vdf`
    - Lutris game YAML folders (`~/.config/lutris/games`, `~/.local/share/lutris/games`)
    - Heroic configuration and store manifests (`~/.config/heroic`)
    - Native desktop application directories (`/usr/share/applications`, `~/.local/share/applications`)
    - Custom filesystem search directories

    Attributes:
        scanner: The active Scanner instance whose cache and providers are updated.
        on_change_callbacks: List of custom callbacks triggered when library changes are observed.
    """

    scanner: Any = None
    poll_interval: float = 1.0
    on_change_callbacks: list[Callable[[list[WatchEvent]], None]] = field(default_factory=list)
    _watcher: FileSystemWatcher = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._watcher = FileSystemWatcher(
            poll_interval=self.poll_interval,
            callback=self._handle_change_events,
        )
        self.register_default_paths()

    def register_default_paths(self) -> None:
        """Register all default provider locations to watch."""
        home = Path.home()
        xdg_config = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
        xdg_data = Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share"))

        paths_to_watch: list[Path] = [
            # Steam manifests
            home / ".steam" / "steam" / "steamapps",
            xdg_data / "Steam" / "steamapps",
            home / ".local" / "share" / "Steam" / "steamapps",
            # Lutris YAMLs
            xdg_config / "lutris" / "games",
            xdg_data / "lutris" / "games",
            # Heroic config
            xdg_config / "heroic",
            xdg_config / "heroic" / "gog_store",
            xdg_config / "heroic" / "legendaryConfig",
            # Native desktop files
            Path("/usr/share/applications"),
            xdg_data / "applications",
            home / ".local" / "share" / "applications",
        ]

        if self.scanner is not None and hasattr(self.scanner, "provider_manager"):
            pm = self.scanner.provider_manager
            # Collect configured search dirs from custom filesystem provider
            if "filesystem" in pm.custom_providers:
                custom_fs = pm.custom_providers["filesystem"]
                if hasattr(custom_fs, "search_dirs"):
                    for d in custom_fs.search_dirs:
                        if isinstance(d, Path):
                            paths_to_watch.append(d)

        for p in paths_to_watch:
            if p.exists():
                self._watcher.add_path(p)

    def start(self) -> None:
        """Start monitoring filesystem changes."""
        self._watcher.start()

    def stop(self) -> None:
        """Stop monitoring filesystem changes."""
        self._watcher.stop()

    def trigger_rescan(self) -> list[Any]:
        """Trigger an immediate incremental rescan on the scanner."""
        if self.scanner is not None:
            logger.info("Filesystem change detected: updating library cache without restarting GameDeck")
            return self.scanner.scan()
        return []

    def _handle_change_events(self, events: list[WatchEvent]) -> None:
        """Handle change event batch and refresh the library cache."""
        logger.info("Observed %d filesystem events across game providers", len(events))
        self.trigger_rescan()
        for cb in self.on_change_callbacks:
            try:
                cb(events)
            except Exception as err:
                logger.error("Error in on_change_callback: %s", err)
