"""Save Game Management system for GameDeck enabling save discovery, backups, and restores."""

from __future__ import annotations

import logging
import os
import shutil
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gamedeck.database import MetadataCache
from gamedeck.models import Game

__all__ = [
    "SaveBackup",
    "SaveManager",
    "CloudSaveProvider",
]

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class SaveBackup:
    """Represents a compressed save game backup snapshot."""

    id: str
    game_id: str
    archive_path: Path
    created_at: str
    size_bytes: int
    notes: str = ""


class CloudSaveProvider:
    """Abstract stub interface for cloud save synchronization (e.g. Nextcloud, WebDAV, rclone)."""

    def is_configured(self) -> bool:
        """Return True if cloud storage backend is configured."""
        return False

    def sync_up(self, backup: SaveBackup) -> bool:
        """Upload local save archive to cloud storage."""
        return False

    def sync_down(self, game_id: str) -> list[SaveBackup]:
        """Download remote save archives for a game."""
        return []


@dataclass(slots=True)
class SaveManager:
    """Manages game save discovery, zip backups, restores, and version history."""

    metadata_cache: MetadataCache = field(default_factory=MetadataCache)

    def get_backup_dir(self) -> Path:
        """Return standard backup directory (~/.local/share/gamedeck/save_backups)."""
        home = Path.home()
        xdg_data = Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share"))
        bdir = xdg_data / "gamedeck" / "save_backups"
        bdir.mkdir(parents=True, exist_ok=True)
        return bdir

    def discover_save_paths(self, game: Game) -> list[Path]:
        """Discover candidate save directories for a game across Steam, Wine, Lutris, and Filesystem."""
        candidates: list[Path] = []
        home = Path.home()

        # 1. Steam userData saves
        if game.source == "steam" and game.appid:
            steam_udata = home / ".local" / "share" / "Steam" / "userdata"
            if steam_udata.is_dir():
                for udir in steam_udata.iterdir():
                    app_save = udir / game.appid
                    if app_save.is_dir():
                        candidates.append(app_save)

        # 2. Wine / Lutris prefix saves
        if game.executable:
            exe_parent = Path(game.executable).parent
            # Look for AppData/Local or Save Games in parent tree
            for ancestor in [exe_parent, exe_parent.parent, exe_parent.parent.parent]:
                for sname in ("Saves", "Save", "saved_games", "SaveData", "AppData"):
                    sp = ancestor / sname
                    if sp.is_dir() and sp not in candidates:
                        candidates.append(sp)

        return candidates

    def create_backup(self, game: Game, save_path: Path, notes: str = "") -> SaveBackup | None:
        """Create a timestamped zip archive backup of a game's save folder."""
        if not save_path.exists():
            logger.warning("Save path '%s' does not exist for backup", save_path)
            return None

        now = datetime.now(timezone.utc)
        timestamp = now.strftime("%Y%m%d_%H%M%S")
        backup_id = f"save_{game.id}_{timestamp}"
        out_zip = self.get_backup_dir() / f"{backup_id}.zip"

        try:
            with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
                if save_path.is_file():
                    zf.write(save_path, save_path.name)
                else:
                    for root, _, files in os.walk(save_path):
                        for f in files:
                            full_p = Path(root) / f
                            rel_p = full_p.relative_to(save_path.parent)
                            zf.write(full_p, str(rel_p))

            size_bytes = out_zip.stat().st_size
            created_at = now.isoformat()

            # Record in SQLite save_backups table
            with self.metadata_cache._get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO save_backups (id, game_id, archive_path, created_at, size_bytes, notes)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (backup_id, game.id, str(out_zip), created_at, size_bytes, notes),
                )

            logger.info("Created save backup '%s' for '%s' (%d bytes)", backup_id, game.name, size_bytes)
            return SaveBackup(
                id=backup_id,
                game_id=game.id,
                archive_path=out_zip,
                created_at=created_at,
                size_bytes=size_bytes,
                notes=notes,
            )
        except Exception as err:
            logger.error("Failed creating save backup for '%s': %s", game.name, err)
            return None

    def list_backups(self, game_id: str) -> list[SaveBackup]:
        """List all save backups for a game sorted by created_at descending."""
        backups: list[SaveBackup] = []
        with self.metadata_cache._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT id, game_id, archive_path, created_at, size_bytes, notes
                FROM save_backups
                WHERE game_id = ?
                ORDER BY created_at DESC
                """,
                (game_id,),
            )
            for row in cursor.fetchall():
                backups.append(
                    SaveBackup(
                        id=row["id"],
                        game_id=row["game_id"],
                        archive_path=Path(row["archive_path"]),
                        created_at=row["created_at"],
                        size_bytes=int(row["size_bytes"]),
                        notes=row["notes"] or "",
                    )
                )
        return backups

    def restore_backup(self, backup: SaveBackup, target_dir: Path) -> bool:
        """Extract a save backup archive into a target directory."""
        if not backup.archive_path.is_file():
            logger.error("Backup archive '%s' not found", backup.archive_path)
            return False

        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(backup.archive_path, "r") as zf:
                zf.extractall(target_dir)
            logger.info("Restored save backup '%s' to '%s'", backup.id, target_dir)
            return True
        except Exception as err:
            logger.error("Failed restoring backup '%s': %s", backup.id, err)
            return False
