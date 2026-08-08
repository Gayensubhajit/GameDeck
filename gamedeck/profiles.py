"""Launch Profiles system for GameDeck enabling multiple runtime configurations per game.

Each game can expose multiple launch profiles (e.g. Lutris, Wine, Steam, Proton Experimental,
Custom ENV / Runner options). Users can switch profiles dynamically or set default profiles.
All profiles are persisted in SQLite without duplicating game provider entries.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gamedeck.database import MetadataCache
from gamedeck.models import Game

__all__ = [
    "LaunchProfile",
    "ProfileManager",
    "get_profiles_for_game",
]

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class LaunchProfile:
    """Represents a specific launcher runtime configuration profile for a game.

    Attributes:
        id: Unique identifier for the profile.
        game_id: Target game identifier.
        name: Clean display name.
        launcher: Execution backend ('lutris', 'wine', 'steam', 'native', 'proton').
        executable: Optional custom executable or override binary path.
        launch_args: Command line parameters or extra arguments.
        env_vars: Dict of custom environment variables.
        use_gamemode: Whether to wrap command with Feral GameMode (gamemoderun).
        use_gamescope: Whether to wrap command with Valve Gamescope compositor.
        use_mangohud: Whether to enable MangoHud performance overlay (MANGOHUD=1).
        use_obs_vkcapture: Whether to enable OBS Vulkan/OpenGL capture (OBS_VKCAPTURE=1).
        pre_launch_script: Optional shell command or script path executed before launch.
        post_exit_script: Optional shell command or script path executed after game exit.
        is_default: Whether this profile is the current default launch target.
        created_at: ISO timestamp.
    """

    id: str
    game_id: str
    name: str
    launcher: str
    executable: Path | None = None
    launch_args: str = ""
    env_vars: dict[str, str] = field(default_factory=dict)
    use_gamemode: bool = False
    use_gamescope: bool = False
    use_mangohud: bool = False
    use_obs_vkcapture: bool = False
    pre_launch_script: str = ""
    post_exit_script: str = ""
    is_default: bool = False
    created_at: str = ""

    @property
    def display_label(self) -> str:
        """Formatted display title with default indicator."""
        default_tag = " [Default]" if self.is_default else ""
        icon = "🚀" if not self.is_default else "⚡"
        return f"{icon}  {self.name} ({self.launcher}){default_tag}"

    def launch(self, game: Game) -> subprocess.Popen[Any] | None:
        """Execute this profile with configured wrappers, launcher, arguments, and environment."""
        merged_env = os.environ.copy()
        for k, v in self.env_vars.items():
            merged_env[k] = str(v)

        if self.use_mangohud:
            merged_env["MANGOHUD"] = "1"
        if self.use_obs_vkcapture:
            merged_env["OBS_VKCAPTURE"] = "1"

        # 0. Pre-launch script
        if self.pre_launch_script and self.pre_launch_script.strip():
            try:
                logger.info("Executing pre-launch script for '%s': %s", game.name, self.pre_launch_script)
                subprocess.run(self.pre_launch_script, shell=True, check=False, env=merged_env)
            except Exception as err:
                logger.error("Pre-launch script failed: %s", err)

        exe_path = self.executable or game.executable
        launcher_type = (self.launcher or game.launcher or "").lower().strip()

        logger.info(
            "Launching '%s' with profile '%s' (runner=%s, exe=%s)",
            game.name,
            self.name,
            launcher_type,
            exe_path,
        )

        base_cmd: list[str] = []

        # 1. Lutris runner
        if launcher_type == "lutris":
            lutris_bin = shutil.which("lutris")
            if lutris_bin:
                slug = game.appid or game.id.removeprefix("lutris_")
                base_cmd = [lutris_bin, f"lutris:rungame/{slug}"]
                if self.launch_args:
                    base_cmd.extend(self.launch_args.split())

        # 2. Steam runner
        elif launcher_type == "steam":
            steam_bin = shutil.which("steam")
            if steam_bin:
                appid = game.appid or "0"
                base_cmd = [steam_bin, f"steam://rungameid/{appid}"]

        # 3. Wine / Proton runners
        elif launcher_type in ("wine", "proton", "proton_experimental", "proton experimental"):
            runner_bin = shutil.which("wine")
            if not runner_bin and exe_path:
                runner_bin = shutil.which(str(exe_path))

            if runner_bin and exe_path:
                base_cmd = [runner_bin, str(exe_path)]
                if self.launch_args:
                    base_cmd.extend(self.launch_args.split())

        # 4. Native Linux application
        elif exe_path and exe_path.exists():
            base_cmd = [str(exe_path)]
            if self.launch_args:
                base_cmd.extend(self.launch_args.split())

        if not base_cmd:
            from gamedeck.launchers import launch
            launch(game)
            return None

        # Build wrapper chain (GameMode, Gamescope)
        final_cmd = list(base_cmd)
        if self.use_gamescope and shutil.which("gamescope"):
            final_cmd = ["gamescope", "-f", "--"] + final_cmd
        if self.use_gamemode and shutil.which("gamemoderun"):
            final_cmd = ["gamemoderun"] + final_cmd

        cwd = str(exe_path.parent) if exe_path and exe_path.exists() and not exe_path.is_dir() else None
        proc = subprocess.Popen(final_cmd, env=merged_env, cwd=cwd)

        # Post-exit script handling if configured
        if self.post_exit_script and self.post_exit_script.strip():
            def _wait_and_post_exit() -> None:
                proc.wait()
                try:
                    logger.info("Executing post-exit script for '%s': %s", game.name, self.post_exit_script)
                    subprocess.run(self.post_exit_script, shell=True, check=False, env=merged_env)
                except Exception as err:
                    logger.error("Post-exit script failed: %s", err)

            import threading
            threading.Thread(target=_wait_and_post_exit, daemon=True).start()

        return proc


@dataclass(slots=True)
class ProfileManager:
    """Manages creation, switching, persistence, and execution of launch profiles in SQLite.

    Attributes:
        metadata_cache: Persistence cache instance.
    """

    metadata_cache: MetadataCache = field(default_factory=MetadataCache)

    def __post_init__(self) -> None:
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        """Create launch_profiles table in SQLite if it does not already exist."""
        with self.metadata_cache._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS launch_profiles (
                    id TEXT PRIMARY KEY,
                    game_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    launcher TEXT NOT NULL,
                    executable TEXT,
                    launch_args TEXT DEFAULT '',
                    env_vars TEXT DEFAULT '',
                    is_default INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_launch_profiles_game ON launch_profiles(game_id)"
            )

    # -------------------------------------------------------------------------
    # Profile Discovery & Generation
    # -------------------------------------------------------------------------

    def get_profiles(self, game: Game) -> list[LaunchProfile]:
        """Retrieve all persisted profiles for a game, generating default built-in alternatives if empty.

        Generates profiles across available runners (e.g. Lutris, Wine, Steam, Proton Experimental)
        without creating duplicate game provider entries.
        """
        profiles = self._get_persisted_profiles(game.id)
        if not profiles:
            # Seed default profile set based on game source and available tools
            profiles = self._generate_default_profiles(game)
            for p in profiles:
                self.save_profile(p)
        return profiles

    def _get_persisted_profiles(self, game_id: str) -> list[LaunchProfile]:
        """Fetch profiles directly from SQLite."""
        profiles: list[LaunchProfile] = []
        with self.metadata_cache._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT id, game_id, name, launcher, executable, launch_args, env_vars,
                       use_gamemode, use_gamescope, use_mangohud, use_obs_vkcapture,
                       pre_launch_script, post_exit_script, is_default, created_at
                FROM launch_profiles
                WHERE game_id = ?
                ORDER BY is_default DESC, name ASC
                """,
                (game_id,),
            )
            for row in cursor.fetchall():
                env_map: dict[str, str] = {}
                raw_env = row["env_vars"]
                if raw_env and raw_env.strip():
                    for pair in raw_env.split(";"):
                        if "=" in pair:
                            k, v = pair.split("=", 1)
                            env_map[k.strip()] = v.strip()

                profiles.append(
                    LaunchProfile(
                        id=row["id"],
                        game_id=row["game_id"],
                        name=row["name"],
                        launcher=row["launcher"],
                        executable=Path(row["executable"]) if row["executable"] else None,
                        launch_args=row["launch_args"] or "",
                        env_vars=env_map,
                        use_gamemode=bool(row["use_gamemode"]) if "use_gamemode" in row.keys() else False,
                        use_gamescope=bool(row["use_gamescope"]) if "use_gamescope" in row.keys() else False,
                        use_mangohud=bool(row["use_mangohud"]) if "use_mangohud" in row.keys() else False,
                        use_obs_vkcapture=bool(row["use_obs_vkcapture"]) if "use_obs_vkcapture" in row.keys() else False,
                        pre_launch_script=row["pre_launch_script"] or "" if "pre_launch_script" in row.keys() else "",
                        post_exit_script=row["post_exit_script"] or "" if "post_exit_script" in row.keys() else "",
                        is_default=bool(row["is_default"]),
                        created_at=row["created_at"],
                    )
                )
        return profiles

    def _generate_default_profiles(self, game: Game) -> list[LaunchProfile]:
        """Generate runner alternatives (Lutris, Wine, Steam, Proton Experimental)."""
        profiles: list[LaunchProfile] = []
        source = (game.source or "").lower().strip()
        launcher = (game.launcher or "").lower().strip()
        now = datetime.now(timezone.utc).isoformat()

        # 1. Primary Native Provider Profile
        primary_name = f"{source.capitalize() if source else 'Default'} Profile"
        profiles.append(
            LaunchProfile(
                id=f"{game.id}_default",
                game_id=game.id,
                name=primary_name,
                launcher=launcher or source or "native",
                executable=game.executable,
                is_default=True,
                created_at=now,
            )
        )

        # 2. Wine profile (if executable exists or windows runner)
        if game.executable is not None or source in ("lutris", "heroic", "filesystem", "wine"):
            profiles.append(
                LaunchProfile(
                    id=f"{game.id}_wine",
                    game_id=game.id,
                    name="Wine Runner",
                    launcher="wine",
                    executable=game.executable,
                    is_default=False,
                    created_at=now,
                )
            )

        # 3. Proton Experimental profile (for Steam/Wine titles)
        if source in ("steam", "lutris", "heroic", "filesystem", "wine"):
            profiles.append(
                LaunchProfile(
                    id=f"{game.id}_proton_exp",
                    game_id=game.id,
                    name="Proton Experimental",
                    launcher="proton",
                    executable=game.executable,
                    env_vars={"PROTON_USE_SECCOMP": "1", "DXVK_ASYNC": "1"},
                    is_default=False,
                    created_at=now,
                )
            )

        # 4. Lutris runner profile (for custom / filesystem / heroic games)
        if source != "lutris":
            profiles.append(
                LaunchProfile(
                    id=f"{game.id}_lutris",
                    game_id=game.id,
                    name="Lutris Runner",
                    launcher="lutris",
                    executable=game.executable,
                    is_default=False,
                    created_at=now,
                )
            )

        return profiles

    # -------------------------------------------------------------------------
    # Profile Persistence & Switching
    # -------------------------------------------------------------------------

    def save_profile(self, profile: LaunchProfile) -> None:
        """Insert or update a launch profile in SQLite."""
        now = profile.created_at or datetime.now(timezone.utc).isoformat()
        env_str = ";".join(f"{k}={v}" for k, v in profile.env_vars.items())

        with self.metadata_cache._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO launch_profiles (
                    id, game_id, name, launcher, executable, launch_args, env_vars,
                    use_gamemode, use_gamescope, use_mangohud, use_obs_vkcapture,
                    pre_launch_script, post_exit_script, is_default, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    launcher = excluded.launcher,
                    executable = excluded.executable,
                    launch_args = excluded.launch_args,
                    env_vars = excluded.env_vars,
                    use_gamemode = excluded.use_gamemode,
                    use_gamescope = excluded.use_gamescope,
                    use_mangohud = excluded.use_mangohud,
                    use_obs_vkcapture = excluded.use_obs_vkcapture,
                    pre_launch_script = excluded.pre_launch_script,
                    post_exit_script = excluded.post_exit_script,
                    is_default = excluded.is_default
                """,
                (
                    profile.id,
                    profile.game_id,
                    profile.name,
                    profile.launcher,
                    str(profile.executable) if profile.executable else None,
                    profile.launch_args,
                    env_str,
                    1 if profile.use_gamemode else 0,
                    1 if profile.use_gamescope else 0,
                    1 if profile.use_mangohud else 0,
                    1 if profile.use_obs_vkcapture else 0,
                    profile.pre_launch_script,
                    profile.post_exit_script,
                    1 if profile.is_default else 0,
                    now,
                ),
            )
            logger.info("Saved launch profile '%s' for game '%s'", profile.name, profile.game_id)

    def set_default_profile(self, game_id: str, profile_id: str) -> bool:
        """Switch the default launch profile for a game in SQLite."""
        with self.metadata_cache._get_connection() as conn:
            # Clear other defaults for this game
            conn.execute("UPDATE launch_profiles SET is_default = 0 WHERE game_id = ?", (game_id,))
            cursor = conn.execute(
                "UPDATE launch_profiles SET is_default = 1 WHERE game_id = ? AND id = ?",
                (game_id, profile_id),
            )
            return cursor.rowcount > 0

    def delete_profile(self, profile_id: str) -> bool:
        """Delete a custom launch profile."""
        with self.metadata_cache._get_connection() as conn:
            cursor = conn.execute("DELETE FROM launch_profiles WHERE id = ?", (profile_id,))
            return cursor.rowcount > 0


def get_profiles_for_game(game: Game, metadata_cache: MetadataCache | None = None) -> list[LaunchProfile]:
    """Convenience helper to retrieve all launch profiles for a game."""
    mgr = ProfileManager(metadata_cache=metadata_cache or MetadataCache())
    return mgr.get_profiles(game)
