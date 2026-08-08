"""Rofi frontend user interface for GameDeck."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gamedeck.models import Game
from gamedeck.ui.artwork_resolver import ArtworkResolver, FALLBACK_ICON, THEME_ICONS
from gamedeck.ui.views import (
    CardStyle,
    GridViewRenderer,
    ListViewRenderer,
    ViewManager,
    ViewMode,
    get_card_style,
)

__all__ = [
    "RofiUI",
    "show_menu",
    "select_game",
    "generate_search_metadata",
    "ViewMode",
    "ViewManager",
    "GridViewRenderer",
    "ListViewRenderer",
]

logger = logging.getLogger(__name__)

_ACTION_ORDER: tuple[str, ...] = (
    "play",
    "launch",
    "toggle_favorite",
    "open_folder",
    "select_profile",
    "configure",
    "browse_prefix",
    "edit_tags",
    "manage_collections",
    "manage_saves",
    "view_screenshots",
    "refresh_metadata",
    "show_properties",
    "edit_properties",
    "remove_from_library",
)

# Standard fallback icon names in Linux desktop icon themes
FALLBACK_ICON: str = "applications-games"
THEME_ICONS: dict[str, str] = {
    "steam": "steam",
    "lutris": "lutris",
    "heroic": "heroic",
    "wine": "wine",
    "proton": "wine",
    "bottles": "com.usebottles.bottles",
    "native": "applications-games",
    "filesystem": "applications-games",
}

from gamedeck.search.tokenizer import tokenize as _search_tokenize


def generate_search_metadata(
    name: str,
    appid: str | None = None,
    source: str | None = None,
    game: Game | None = None,
    favorite: bool = False,
    installed: bool = False,
    tags: list[str] | None = None,
    collections: list[str] | None = None,
) -> str:
    """Generate search keywords including abbreviations, compact forms, normalized tokens, tags, and collections."""
    launcher = None
    executable = None

    if game is not None:
        favorite = game.favorite
        installed = game.installed
        launcher = game.launcher
        executable = game.executable
        if getattr(game, "tags", None):
            tags = game.tags
        if getattr(game, "collections", None):
            collections = game.collections

    tokens = set(_search_tokenize(
        name=name,
        appid=appid,
        source=source,
        launcher=launcher,
        executable=executable,
        tags=tags,
        collections=collections,
    ))

    if favorite:
        tokens.update(["favorite", "favorites", "star", "starred"])
    if installed:
        tokens.add("installed")

    return " ".join(sorted(tokens))


def _calc_rofi_lines(count: int, max_lines: int = 12) -> str:
    """Calculate dynamic -lines argument for Rofi to eliminate empty vertical space."""
    return str(min(max(count, 1), max_lines))


@dataclass(slots=True)
class RofiUI:
    """Rofi dmenu-based graphical launcher interface for selecting games.

    Presents a searchable, interactive menu of games with favorite star indicators (★),
    dynamic window sizing, icon resolution, and keyboard-first workflow.

    Attributes:
        prompt: Display prompt text shown in the Rofi search bar.
        theme: Optional path to a custom Rofi .rasi theme file.
        theme_str: Optional inline .rasi theme string to customize styling.
        show_icons: Whether to enable and send icon paths/names to Rofi.
        case_insensitive: Whether search matching should be case-insensitive.
        matching: Rofi matching algorithm (fuzzy, normal, regex, glob).
        sorting_method: Rofi sorting algorithm (fzf, normal).
        enable_action_menu: Whether Alt+Return opens the action menu (Enter launches directly).
        rofi_bin: Name or absolute path of the Rofi executable.
        secondary_action_key: Rofi custom-1 keybinding to open the action menu.
    """

    prompt: str = "GameDeck > Library"
    theme: Path | str | None = None
    theme_str: str | None = None
    show_icons: bool = True
    case_insensitive: bool = True
    matching: str = "fuzzy"
    sorting_method: str = "fzf"
    enable_action_menu: bool = True
    quick_launch: bool = True
    rofi_bin: str = "rofi"
    secondary_action_key: str = "Alt+Return"
    default_view: str = "deck"
    grid_columns: int = 6
    grid_card_style: str = "deck"
    db_cache: Any = None
    view_manager: ViewManager | None = None

    def _ensure_view_manager(self) -> ViewManager:
        """Initialize or retrieve the ViewManager instance."""
        if self.view_manager is None:
            resolver = ArtworkResolver()
            self.view_manager = ViewManager(
                default_view=self.default_view,
                grid_columns=self.grid_columns,
                grid_card_style=self.grid_card_style,
                artwork_resolver=resolver,
                db_cache=self.db_cache,
            )
        return self.view_manager

    @property
    def active_view_mode(self) -> ViewMode:
        """Get the current active view mode."""
        return self._ensure_view_manager().active_mode

    def switch_to_list(self) -> None:
        """Switch active view mode to List View."""
        self._ensure_view_manager().switch_to_list()

    def switch_to_grid(self) -> None:
        """Switch active view mode to Grid View."""
        self._ensure_view_manager().switch_to_grid()

    def switch_to_view(self, view_name: str | ViewMode) -> None:
        """Switch active view mode to any supported pluggable view."""
        self._ensure_view_manager().switch_to(view_name)

    def _get_base_cmd(self, prompt_text: str, lines_count: int) -> tuple[list[str], str]:
        """Construct standard command line arguments and executable path for Rofi."""
        executable = shutil.which(self.rofi_bin)
        if executable is None:
            raise RuntimeError(
                f"Rofi executable '{self.rofi_bin}' was not found in PATH. "
                "Please install Rofi or Rofi-Wayland to use the GameDeck UI."
            )

        cmd: list[str] = [
            executable,
            "-dmenu",
            "-p",
            prompt_text,
            "-format",
            "i",
            "-matching",
            self.matching,
            "-sort",
            "-sorting-method",
            self.sorting_method,
            "-lines",
            _calc_rofi_lines(lines_count),
        ]

        if self.case_insensitive:
            cmd.append("-i")

        if self.show_icons:
            cmd.append("-show-icons")

        base_dialog_rasi = """
* {
    background-color: transparent;
    text-color: #e2e8f0;
    font: "Outfit 11";
    accent: #00e699;
}

window {
    width: 52%;
    location: center;
    anchor: center;
    border: 1.5px solid;
    border-color: #00e69944;
    border-radius: 18px;
    background-color: #0c1412f6;
    padding: 18px;
}

mainbox {
    spacing: 12px;
    children: [ inputbar, message, listview ];
    background-color: transparent;
}

inputbar {
    background-color: #14201ce0;
    border: 1px solid;
    border-color: #00e69944;
    border-radius: 12px;
    padding: 10px 16px;
    spacing: 12px;
    children: [ prompt, entry ];
}

prompt {
    text-color: #00e699;
    font: "Outfit Bold 11";
    background-color: transparent;
}

entry {
    text-color: #f0fdf4;
    font: "Outfit Regular 11";
    placeholder: "Type to filter options...";
    placeholder-color: #64748b;
    background-color: transparent;
}

message {
    background-color: #14201cc8;
    border: 1px solid;
    border-color: #00e69933;
    border-radius: 12px;
    padding: 10px 16px;
}

textbox {
    text-color: #94a3b8;
    font: "Outfit Regular 9.5";
    background-color: transparent;
}

listview {
    layout: vertical;
    spacing: 6px;
    cycle: true;
    dynamic: true;
    scrollbar: false;
    background-color: transparent;
}

element {
    orientation: horizontal;
    children: [ element-icon, element-text ];
    spacing: 12px;
    padding: 8px 12px;
    border-radius: 10px;
    background-color: #14201ca0;
    border: 1px solid;
    border-color: #24383260;
    text-color: #cbd5e1;
}

element selected {
    background-color: #00e69926;
    border: 1.5px solid;
    border-color: #00e699;
    text-color: #00e699;
}

element-icon {
    size: 22px;
    vertical-align: 0.5;
    background-color: transparent;
}

element-text {
    vertical-align: 0.5;
    font: "Outfit Medium 10.5";
    text-color: inherit;
    background-color: transparent;
}
"""
        if self.theme is not None:
            cmd.extend(["-theme", str(self.theme)])
        elif self.theme_str is not None and self.theme_str.strip():
            cmd.extend(["-theme-str", self.theme_str.strip()])
        else:
            cmd.extend(["-theme-str", base_dialog_rasi.strip()])

        return cmd, executable

    def select(
        self,
        games: list[Game],
        dynamic_collections: list[Any] | None = None,
        custom_collections: list[Any] | None = None,
        prompt: str | None = None,
    ) -> Game | Any | None:
        """Display games in the user's preferred view (List or Grid) and return selection."""
        if not games:
            return None

        prompt_str = prompt or f"GameDeck  •  Library  •  Grid View  •  {len(games)} Games"
        vm = self._ensure_view_manager()

        while True:
            # 1. Pluggable Graphic/Grid Views (Grid, Deck, Compact, Hero, Carousel)
            if vm.active_mode != ViewMode.LIST:
                active_view = vm.active_view
                view_prompt = prompt if prompt else (None if active_view.name == "deck" else f"GameDeck  •  Library  •  {active_view.display_name}  •  {len(games)} Games")
                selected, ret_code, action_trigger = vm.render(
                    games=games,
                    prompt=view_prompt,
                    theme_path=self.theme,
                    theme_str=self.theme_str,
                )

                if action_trigger.startswith("switch_view_"):
                    target = action_trigger.replace("switch_view_", "")
                    logger.info("User switched view to %s", target)
                    vm.switch_to(target)
                    continue
                elif action_trigger == "refresh":
                    return "NAV_STATS"
                elif action_trigger == "action_menu" and selected is not None:
                    return (selected, "SECONDARY_KEY")
                elif action_trigger == "launch" and selected is not None:
                    return selected
                else:
                    return None

            # 2. Classic List View Mode
            else:
                use_custom_key = bool(self.secondary_action_key and self.enable_action_menu)
                lines: list[str] = []
                name_map: dict[str, Game] = {}
                nav_by_index: list[Any] = []

                def _append_nav(
                    display: str,
                    marker: str,
                    payload: Any,
                    *,
                    meta: str | None = None,
                ) -> None:
                    parts = [display, f"info\x1f{marker}"]
                    if meta:
                        parts.append(f"meta\x1f{meta}")
                    lines.append(f"{parts[0]}\0{'\x1f'.join(parts[1:])}")
                    nav_by_index.append(payload)

                # Main menu top navigation submenus
                _append_nav(
                    "📁  Collections...",
                    "nav_collections",
                    "NAV_COLLECTIONS",
                    meta="collections library provider steam lutris heroic custom",
                )
                _append_nav(
                    "🏷  Filter by Tag...",
                    "nav_tags",
                    "NAV_TAGS",
                    meta="tags rpg soulslike fps indie coop finished wishlist",
                )
                _append_nav(
                    "📊  Library Stats",
                    "nav_stats",
                    "NAV_STATS",
                    meta="stats statistics playtime launches favorites total library",
                )

                nav_count = len(lines)

                for idx, game in enumerate(games):
                    base_title = game.name.strip() if game.name else f"Game #{idx + 1}"
                    display_title = f"★  {base_title}" if game.favorite else base_title
                    name_map[display_title] = game

                    meta_keywords = generate_search_metadata(
                        name=game.name,
                        appid=game.appid,
                        source=game.source,
                        game=game,
                    )

                    icon_spec = self.resolve_game_icon(game) if self.show_icons else None

                    parts = [display_title, f"meta\x1f{meta_keywords}", f"info\x1fgame:{idx}"]
                    if icon_spec:
                        parts.insert(1, f"icon\x1f{icon_spec}")

                    line = f"{parts[0]}\0{'\x1f'.join(parts[1:])}"
                    lines.append(line)

                cmd, _ = self._get_base_cmd(prompt_str, len(lines))

                if not use_custom_key:
                    cmd.append("-no-custom")
                else:
                    cmd.extend(["-kb-custom-1", self.secondary_action_key])

                cmd.extend([
                    "-kb-custom-2", "Control+1",
                    "-kb-custom-3", "Control+2",
                    "-kb-custom-4", "F5",
                    "-mesg", "<b>Enter</b> Play  •  <b>Alt</b> Options  •  <b>Ctrl+1</b> List  •  <b>Ctrl+2</b> Grid  •  <b>Ctrl+F</b> Search  •  <b>Esc</b> Back  •  <b>F5</b> Refresh",
                ])

                input_payload = "\n".join(lines) + "\n"
                logger.debug("Opening Rofi menu with %d nav items and %d games", nav_count, len(games))

                try:
                    result = subprocess.run(
                        cmd,
                        input=input_payload,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        check=False,
                    )
                except OSError as err:
                    logger.error("Failed to execute Rofi process: %s", err)
                    raise RuntimeError(f"Failed to execute Rofi: {err}") from err

                # Handle view switching shortcuts
                if result.returncode == 11:
                    logger.info("User requested List View via Ctrl+1")
                    vm.switch_to_list()
                    continue
                elif result.returncode == 12:
                    logger.info("User requested Grid View via Ctrl+2")
                    vm.switch_to_grid()
                    continue
                elif result.returncode == 14:
                    return "NAV_STATS"
                elif result.returncode not in (0, 10):
                    logger.debug("Rofi selection cancelled (returncode=%d)", result.returncode)
                    return None

                output = result.stdout.strip()
                if not output:
                    return None

                open_actions = result.returncode == 10

                if output.isdigit():
                    selected_idx = int(output)
                    if 0 <= selected_idx < nav_count:
                        nav_payload = nav_by_index[selected_idx]
                        if open_actions:
                            return None
                        return nav_payload

                    game_idx = selected_idx - nav_count
                    if 0 <= game_idx < len(games):
                        selected = games[game_idx]
                        logger.info("User selected game: %s [%s]", selected.name, selected.id)
                        if open_actions:
                            return (selected, "SECONDARY_KEY")
                        return selected

                selected = name_map.get(output)
                if selected is not None:
                    logger.info("User selected game (title match): %s [%s]", selected.name, selected.id)
                    if open_actions:
                        return (selected, "SECONDARY_KEY")
                    return selected

                return None

    def select_game_action(self, game: Game, prompt: str | None = None) -> tuple[str, Any]:
        """Display dynamic context action menu for the chosen game in preferred usability order.

        A rich information panel is shown as a Rofi message header (above the action list)
        so the user sees Launcher, Platform, Last Played, Playtime, Favorite, Tags, and
        Collections immediately — no extra navigation required.
        """
        from gamedeck.actions import GameAction, get_actions_for_game

        executable = shutil.which(self.rofi_bin)
        if executable is None:
            return ("launch", None)

        prompt_str = prompt or f"GameDeck > {game.name}"
        dynamic_actions = get_actions_for_game(game)

        # Build clean action list in preferred order without non-selectable line dividers
        items: list[str] = []
        action_at_index: list[GameAction | None] = []

        action_map = {a.id: a for a in dynamic_actions}

        for act_id in _ACTION_ORDER:
            if act_id not in action_map:
                continue
            act = action_map[act_id]

            if act.id in ("play", "launch"):
                items.append("▶  Play")
            elif act.id == "toggle_favorite":
                label = "★  Unfavorite" if game.favorite else "★  Favorite"
                items.append(label)
            elif act.id == "open_folder":
                items.append("📁  Open Folder")
            elif act.id == "select_profile":
                items.append("⚡  Launch Profiles")
            elif act.id == "configure":
                items.append("⚙  Configure")
            elif act.id == "browse_prefix":
                items.append("🍷  Browse Prefix")
            elif act.id == "edit_tags":
                items.append("🏷  Edit Tags")
            elif act.id == "manage_collections":
                items.append("📁  Manage Collections")
            elif act.id == "manage_saves":
                items.append("💾  Save Backups")
            elif act.id == "view_screenshots":
                items.append("🖼  Screenshots")
            elif act.id == "refresh_metadata":
                items.append("🔄  Refresh Metadata / Artwork")
            elif act.id == "show_properties":
                items.append("📋  Full Details")
            elif act.id == "edit_properties":
                items.append("✏️  Edit Properties")
            else:
                items.append(act.display_text)

            action_at_index.append(act)

        items.append("←  Back")
        action_at_index.append(None)

        cmd, _ = self._get_base_cmd(prompt_str, len(items))
        cmd.append("-no-custom")

        # Build rich info panel shown as Rofi -mesg header above the action list
        info_lines = self._build_game_info_mesg(game)
        if info_lines:
            cmd.extend(["-mesg", info_lines])

        input_payload = "\n".join(items) + "\n"

        try:
            result = subprocess.run(
                cmd,
                input=input_payload,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except OSError as err:
            logger.error("Failed to execute Rofi action dialog: %s", err)
            return ("launch", None)

        if result.returncode != 0:
            return ("back", None)

        raw_idx = result.stdout.strip()
        try:
            idx = int(raw_idx)
        except ValueError:
            idx = -1

        if 0 <= idx < len(action_at_index):
            chosen_action = action_at_index[idx]
            if chosen_action is None:
                return ("back", None)
            if chosen_action.id == "toggle_favorite":
                return ("toggle_favorite", chosen_action)
            elif chosen_action.id == "select_profile":
                return ("select_profile", chosen_action)
            elif chosen_action.id == "manage_collections":
                return ("manage_collections", chosen_action)
            elif chosen_action.id == "manage_saves":
                return ("manage_saves", chosen_action)
            elif chosen_action.id == "view_screenshots":
                return ("view_screenshots", chosen_action)
            elif chosen_action.id == "edit_tags":
                return ("edit_tags", chosen_action)
            elif chosen_action.id == "show_properties":
                return ("show_details", chosen_action)
            elif chosen_action.id == "edit_properties":
                return ("edit_properties", chosen_action)
            elif chosen_action.id == "refresh_metadata":
                return ("refresh_metadata", chosen_action)
            elif chosen_action.id == "remove_from_library":
                return ("remove_from_library", chosen_action)
            elif chosen_action.is_primary or chosen_action.id in ("play", "launch"):
                return ("launch", chosen_action)
            return ("execute_action", chosen_action)

        return ("back", None)

    def _build_game_info_mesg(self, game: Game) -> str:
        """Build a compact rich information string for display as Rofi -mesg header.

        Shows key game details inline in the action menu so no extra navigation is needed
        to see Launcher, Platform, Executable, Last Played, Playtime, Favorite, Tags.
        """
        lines: list[str] = []

        # Source & Launcher
        source = game.source.capitalize() if game.source else "Unknown"
        launcher = game.launcher if game.launcher else "native"
        lines.append(f"<b>Source:</b> {source}  •  <b>Launcher:</b> {launcher}")

        # Platform
        platform = getattr(game, "platform", None)
        if not platform:
            src_lower = (game.source or "").lower()
            lnc_lower = (game.launcher or "").lower()
            if lnc_lower in ("wine", "proton", "bottles") or src_lower in ("heroic",):
                platform = "Windows (Wine/Proton)"
            elif src_lower == "steam":
                platform = "Steam (Linux/Proton)"
            else:
                platform = "Linux Native"
        lines.append(f"<b>Platform:</b> {platform}")

        # Executable path (shortened for display)
        if game.executable:
            exe_path = str(game.executable)
            if len(exe_path) > 60:
                exe_path = "…" + exe_path[-57:]
            lines.append(f"<b>Executable:</b> {exe_path}")

        # Wine/Proton version
        wine_version = getattr(game, "wine_version", None)
        if wine_version:
            lines.append(f"<b>Runner:</b> {wine_version}")

        # Version
        version = getattr(game, "version", None)
        if version:
            lines.append(f"<b>Version:</b> {version}")

        # Playtime
        playtime = getattr(game, "playtime_minutes", 0) or 0
        if playtime > 0:
            hrs, mins = divmod(playtime, 60)
            pt_str = f"{hrs}h {mins}m" if hrs else f"{mins}m"
            lines.append(f"<b>Playtime:</b> {pt_str}")

        # Last played & launch count
        last = game.last_played
        last_str = last[:10] if last else "Never"
        fav_icon = "★" if game.favorite else "☆"
        lines.append(f"<b>Last Played:</b> {last_str}  •  <b>Launches:</b> {game.launch_count}  •  {fav_icon}")

        # Tags
        tags = getattr(game, "tags", None) or []
        if tags:
            lines.append(f"<b>Tags:</b> {',  '.join(tags)}")

        # Collections
        collections = getattr(game, "collections", None) or []
        if collections:
            lines.append(f"<b>Collections:</b> {',  '.join(collections)}")

        # Notes
        notes = getattr(game, "notes", None)
        if notes:
            lines.append(f"<b>Notes:</b> {notes}")

        return "\n".join(lines)

    def show_select_profile_dialog(self, profiles: list[Any], game_name: str, prompt: str | None = None) -> tuple[str, Any | None]:
        """Show launch profile selector dialog."""
        executable = shutil.which(self.rofi_bin)
        if executable is None:
            return ("cancel", None)

        prompt_str = prompt or f"{game_name} > Launch Profiles"
        items: list[str] = []

        if profiles:
            for p in profiles:
                items.append(f"⚡  {p.display_label}")

        items.append("➕  Create Custom Profile...")
        items.append("⬅  Done / Back")

        cmd, _ = self._get_base_cmd(prompt_str, len(items))
        cmd.append("-no-custom")

        input_payload = "\n".join(items) + "\n"

        try:
            result = subprocess.run(
                cmd,
                input=input_payload,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except OSError:
            return ("cancel", None)

        if result.returncode != 0:
            return ("cancel", None)

        raw = result.stdout.strip()
        try:
            idx = int(raw)
        except ValueError:
            return ("cancel", None)

        num_profiles = len(profiles)
        if 0 <= idx < num_profiles:
            return ("configure_profile", profiles[idx])

        if idx == num_profiles:
            return ("prompt_new_profile", None)

        return ("done", None)

    def show_configure_profile_dialog(self, profile: Any, game_name: str, prompt: str | None = None) -> tuple[str, str | None]:
        """Show interactive wrapper configuration menu for a launch profile.

        Allows setting default status, GameMode, Gamescope, MangoHud, OBS VkCapture, and pre/post scripts.
        """
        executable = shutil.which(self.rofi_bin)
        if executable is None:
            return ("cancel", None)

        prompt_str = prompt or f"{profile.name} > Wrappers & Settings"
        gm_status = "[ON]" if getattr(profile, "use_gamemode", False) else "[OFF]"
        gs_status = "[ON]" if getattr(profile, "use_gamescope", False) else "[OFF]"
        mh_status = "[ON]" if getattr(profile, "use_mangohud", False) else "[OFF]"
        obs_status = "[ON]" if getattr(profile, "use_obs_vkcapture", False) else "[OFF]"
        def_status = "★  Default Profile" if getattr(profile, "is_default", False) else "⭐  Set as Default Profile"

        items = [
            def_status,
            f"⚡  Toggle GameMode (gamemoderun) {gm_status}",
            f"🎮  Toggle Gamescope Compositor {gs_status}",
            f"📊  Toggle MangoHud Overlay {mh_status}",
            f"🎥  Toggle OBS VkCapture {obs_status}",
            f"📝  Set Pre-launch Script ({getattr(profile, 'pre_launch_script', '') or 'None'})",
            f"🏁  Set Post-exit Script ({getattr(profile, 'post_exit_script', '') or 'None'})",
            "⬅  Done / Save",
        ]

        action_keys = [
            "set_default",
            "toggle_gamemode",
            "toggle_gamescope",
            "toggle_mangohud",
            "toggle_obs",
            "edit_pre_script",
            "edit_post_script",
            "done",
        ]

        cmd, _ = self._get_base_cmd(prompt_str, len(items))
        cmd.append("-no-custom")

        input_payload = "\n".join(items) + "\n"

        try:
            result = subprocess.run(
                cmd,
                input=input_payload,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except OSError:
            return ("cancel", None)

        if result.returncode != 0:
            return ("cancel", None)

        raw = result.stdout.strip()
        try:
            idx = int(raw)
        except ValueError:
            return ("cancel", None)

        if 0 <= idx < len(action_keys):
            return (action_keys[idx], None)

        return ("done", None)

    def show_edit_properties_dialog(self, game: Game, prompt: str | None = None) -> tuple[str, str | None]:
        """Show interactive properties editor dialog for a game."""
        executable = shutil.which(self.rofi_bin)
        if executable is None:
            return ("cancel", None)

        prompt_str = prompt or f"{game.name} > Edit Properties"
        exe_str = str(game.executable) if game.executable else "None"
        icon_str = str(game.icon) if game.icon else "Default"
        cover_str = str(game.cover) if game.cover else "None"
        logo_str = str(game.logo) if game.logo else "None"
        hero_str = str(game.hero) if game.hero else "None"

        items = [
            f"✏️  Title: {game.name}",
            f"⚙️  Executable: {exe_str}",
            f"🚀  Launcher Runner: {game.launcher}",
            f"🖼️  Icon Path: {icon_str}",
            f"🎨  Cover Art: {cover_str}",
            f"✨  Logo Art: {logo_str}",
            f"🌄  Hero Banner: {hero_str}",
            "⬅  Done / Back",
        ]

        cmd, _ = self._get_base_cmd(prompt_str, len(items))
        cmd.append("-no-custom")

        input_payload = "\n".join(items) + "\n"

        try:
            result = subprocess.run(
                cmd,
                input=input_payload,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except OSError:
            return ("cancel", None)

        if result.returncode != 0:
            return ("cancel", None)

        raw = result.stdout.strip()
        try:
            idx = int(raw)
        except ValueError:
            return ("cancel", None)

        if idx == 0:
            new_title = self.prompt_text(f"New Title (current: {game.name}):")
            if new_title and new_title.strip():
                return ("edit_title", new_title.strip())
        elif idx == 1:
            new_exe = self.prompt_text("New Executable Path:")
            if new_exe and new_exe.strip():
                return ("edit_executable", new_exe.strip())
        elif idx == 2:
            new_launcher = self.prompt_text(f"New Launcher (current: {game.launcher}):")
            if new_launcher and new_launcher.strip():
                return ("edit_launcher", new_launcher.strip())
        elif idx == 3:
            new_icon = self.prompt_text("New Icon File Path (PNG/SVG/XPM):")
            if new_icon and new_icon.strip():
                return ("edit_icon", new_icon.strip())
        elif idx == 4:
            new_cover = self.prompt_text("New Cover Art File Path (PNG/JPG):")
            if new_cover and new_cover.strip():
                return ("edit_cover", new_cover.strip())
        elif idx == 5:
            new_logo = self.prompt_text("New Logo Art File Path (PNG):")
            if new_logo and new_logo.strip():
                return ("edit_logo", new_logo.strip())
        elif idx == 6:
            new_hero = self.prompt_text("New Hero Banner File Path (PNG/JPG):")
            if new_hero and new_hero.strip():
                return ("edit_hero", new_hero.strip())

        return ("done", None)

    def show_edit_tags_dialog(
        self,
        all_tags: list[Any],
        game_tag_names: list[str],
        game_name: str,
        prompt: str | None = None,
    ) -> tuple[str, str | None]:
        """Show interactive tag assignment dialog for a game."""
        executable = shutil.which(self.rofi_bin)
        if executable is None:
            return ("cancel", None)

        prompt_str = prompt or f"{game_name} > Edit Tags"
        items: list[str] = []
        tag_names: list[str] = []
        current_set = set(game_tag_names)

        if all_tags:
            for t in all_tags:
                is_tagged = t.name in current_set
                check = "☑" if is_tagged else "☐"
                items.append(f"{check}  {t.name}")
                tag_names.append(t.name)

        items.append("➕  Add Custom Tag...")
        items.append("⬅  Done / Back")

        cmd, _ = self._get_base_cmd(prompt_str, len(items))
        cmd.append("-no-custom")

        input_payload = "\n".join(items) + "\n"

        try:
            result = subprocess.run(
                cmd,
                input=input_payload,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except OSError:
            return ("cancel", None)

        if result.returncode != 0:
            return ("cancel", None)

        raw = result.stdout.strip()
        try:
            idx = int(raw)
        except ValueError:
            return ("cancel", None)

        num_tags = len(all_tags)
        if 0 <= idx < num_tags:
            target_tag = tag_names[idx]
            if target_tag in current_set:
                return ("remove_tag", target_tag)
            return ("add_tag", target_tag)

        if idx == num_tags:
            return ("prompt_new_tag", None)

        return ("done", None)

    def show_manage_collections_dialog(
        self,
        custom_collections: list[Any],
        game_member_cids: set[str],
        game_name: str,
        prompt: str | None = None,
    ) -> tuple[str, str | None]:
        """Show interactive collection management dialog for a specific game."""
        executable = shutil.which(self.rofi_bin)
        if executable is None:
            return ("cancel", None)

        prompt_str = prompt or f"{game_name} > Manage Collections"
        items: list[str] = []
        cids: list[str] = []

        if custom_collections:
            for coll in custom_collections:
                is_in = coll.id in game_member_cids
                check = "☑" if is_in else "☐"
                items.append(f"{check}  {coll.name}")
                cids.append(coll.id)

        items.append("➕  Create New Collection...")
        items.append("⬅  Done / Back")

        cmd, _ = self._get_base_cmd(prompt_str, len(items))
        cmd.append("-no-custom")

        input_payload = "\n".join(items) + "\n"

        try:
            result = subprocess.run(
                cmd,
                input=input_payload,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except OSError:
            return ("cancel", None)

        if result.returncode != 0:
            return ("cancel", None)

        raw = result.stdout.strip()
        try:
            idx = int(raw)
        except ValueError:
            return ("cancel", None)

        num_colls = len(custom_collections)
        if 0 <= idx < num_colls:
            target_cid = cids[idx]
            if target_cid in game_member_cids:
                return ("remove_from_collection", target_cid)
            return ("add_to_collection", target_cid)

        if idx == num_colls:
            return ("prompt_new_collection", None)

        return ("done", None)

    def prompt_text(self, prompt_label: str) -> str | None:
        """Prompt user for a single line of text input via Rofi."""
        executable = shutil.which(self.rofi_bin)
        if executable is None:
            return None

        cmd: list[str] = [
            executable,
            "-dmenu",
            "-p",
            prompt_label,
            "-lines",
            "0",
        ]
        if self.theme is not None:
            cmd.extend(["-theme", str(self.theme)])
        elif self.theme_str is not None and self.theme_str.strip():
            cmd.extend(["-theme-str", self.theme_str.strip()])

        try:
            result = subprocess.run(
                cmd,
                input="",
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            if result.returncode == 0:
                text = result.stdout.strip()
                return text if text else None
        except OSError:
            pass
        return None

    def show_game_details_dialog(self, summary_text: str, game_name: str, prompt: str | None = None) -> None:
        """Display a read-only metadata summary card dialog for a game in Rofi.

        Each line of the summary is shown as a non-selectable list entry so the
        user can scroll through details before pressing Escape or Enter to go back.
        """
        executable = shutil.which(self.rofi_bin)
        if executable is None:
            return

        prompt_str = prompt or f"{game_name} > Details"

        # Display each line of the summary as a list entry for readability
        detail_lines = [line for line in summary_text.splitlines() if line.strip()]
        detail_lines.append("⬅  Back / Close")

        cmd, _ = self._get_base_cmd(prompt_str, len(detail_lines))
        cmd.append("-no-custom")

        if self.theme is not None:
            pass  # already applied by _get_base_cmd
        elif self.theme_str is not None and self.theme_str.strip():
            pass  # already applied by _get_base_cmd

        input_payload = "\n".join(detail_lines) + "\n"

        try:
            subprocess.run(
                cmd,
                input=input_payload,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except OSError:
            pass

    def show_saves_dialog(self, backups: list[Any], game_name: str, prompt: str | None = None) -> tuple[str, Any | None]:
        """Show Save Management dialog with Create Backup and Restore options."""
        executable = shutil.which(self.rofi_bin)
        if executable is None:
            return ("cancel", None)

        prompt_str = prompt or f"{game_name} > Save Backups"
        items: list[str] = ["➕  Create Save Backup..."]
        items_by_index: list[Any] = ["create_backup"]

        if backups:
            for b in backups:
                sz = f"({b.size_bytes // 1024} KB)" if getattr(b, "size_bytes", 0) > 0 else ""
                items.append(f"📦  Restore: {b.created_at[:19]} {sz}")
                items_by_index.append(b)

        items.append("←  Back")
        items_by_index.append("back")

        cmd, _ = self._get_base_cmd(prompt_str, len(items))
        cmd.append("-no-custom")

        input_payload = "\n".join(items) + "\n"

        try:
            result = subprocess.run(
                cmd,
                input=input_payload,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except OSError:
            return ("cancel", None)

        if result.returncode != 0:
            return ("cancel", None)

        output = result.stdout.strip()
        if output.isdigit():
            idx = int(output)
            if 0 <= idx < len(items_by_index):
                payload = items_by_index[idx]
                if payload == "create_backup":
                    return ("create_backup", None)
                elif payload == "back":
                    return ("cancel", None)
                return ("restore_backup", payload)

        return ("cancel", None)

    def show_screenshots_dialog(self, screenshots: list[Any], game_name: str, prompt: str | None = None) -> None:
        """Display screenshots list dialog in Rofi."""
        executable = shutil.which(self.rofi_bin)
        if executable is None:
            return

        prompt_str = prompt or f"{game_name} > Screenshots"
        items: list[str] = []

        if screenshots:
            for sc in screenshots:
                items.append(f"🖼  {sc.file_path.name} ({sc.created_at[:10]})")
        else:
            items.append("No screenshots discovered for this game.")

        items.append("←  Back")

        cmd, _ = self._get_base_cmd(prompt_str, len(items))
        cmd.append("-no-custom")

        input_payload = "\n".join(items) + "\n"

        try:
            subprocess.run(
                cmd,
                input=input_payload,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except OSError:
            pass

    def select_tag(self, tags: list[Any], prompt: str | None = None) -> Any | None:
        """Present a menu of game tags."""
        executable = shutil.which(self.rofi_bin)
        if executable is None:
            return None

        prompt_str = prompt or "GameDeck > Filter by Tag"
        visible_tags = [t for t in tags if getattr(t, "count", 0) > 0] if tags else []

        lines: list[str] = []
        name_map: dict[str, Any] = {}
        items_by_index: list[Any] = []

        if visible_tags:
            for t in visible_tags:
                display_title = f"🏷  {t.name} ({t.count})"
                name_map[display_title] = t
                lines.append(f"{display_title}\0info\x1ftag:{t.name}")
                items_by_index.append(t)

        lines.append("←  Back\0info\x1fback")
        items_by_index.append("BACK")

        cmd, _ = self._get_base_cmd(prompt_str, len(lines))
        cmd.append("-no-custom")

        input_payload = "\n".join(lines) + "\n"

        try:
            result = subprocess.run(
                cmd,
                input=input_payload,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except OSError:
            return None

        if result.returncode != 0:
            return None

        output = result.stdout.strip()
        if output.isdigit():
            idx = int(output)
            if 0 <= idx < len(items_by_index):
                payload = items_by_index[idx]
                if payload == "BACK":
                    return None
                return payload

        return name_map.get(output)

    def select_collection(self, collections: list[Any], prompt: str | None = None) -> Any | None:
        """Present a menu of game collections."""
        executable = shutil.which(self.rofi_bin)
        if executable is None:
            return None

        prompt_str = prompt or "GameDeck > Collections"
        lines: list[str] = []
        name_map: dict[str, Any] = {}
        items_by_index: list[Any] = []

        visible = [c for c in collections if c.count() > 0] if collections else []
        dynamic = [c for c in visible if c.is_dynamic]
        custom = [c for c in visible if not c.is_dynamic]

        system_icons: dict[str, str] = {
            "favorites": "★",
            "installed": "🎮",
            "lutris": "🍷",
            "native": "🐧",
            "steam": "🟦",
            "heroic": "🟥",
            "recently_played": "🕒",
        }

        if dynamic:
            for coll in dynamic:
                icon = system_icons.get(coll.id.lower(), coll.icon)
                display_title = f"{icon}  {coll.name} ({coll.count()})"
                name_map[display_title] = coll
                lines.append(f"{display_title}\0info\x1fcoll:{coll.id}")
                items_by_index.append(coll)

        if custom:
            for coll in custom:
                display_title = f"📁  {coll.name} ({coll.count()})"
                name_map[display_title] = coll
                lines.append(f"{display_title}\0info\x1fcoll:{coll.id}")
                items_by_index.append(coll)

        lines.append("➕  Create Collection...\0info\x1fcreate")
        items_by_index.append("NAV_CREATE_COLLECTION")

        lines.append("←  Back\0info\x1fback")
        items_by_index.append("BACK")

        cmd, _ = self._get_base_cmd(prompt_str, len(lines))
        cmd.append("-no-custom")

        input_payload = "\n".join(lines) + "\n"

        try:
            result = subprocess.run(
                cmd,
                input=input_payload,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except OSError:
            return None

        if result.returncode != 0:
            return None

        output = result.stdout.strip()
        if output.isdigit():
            idx = int(output)
            if 0 <= idx < len(items_by_index):
                payload = items_by_index[idx]
                if payload == "BACK":
                    return None
                return payload

        if output in name_map:
            return name_map[output]
        if output == "➕  Create Collection...":
            return "NAV_CREATE_COLLECTION"

        return None

    def select_with_action(
        self,
        games: list[Game],
        dynamic_collections: list[Any] | None = None,
        custom_collections: list[Any] | None = None,
        prompt: str | None = None,
    ) -> tuple[Game | Any | None, str | tuple[str, Any]]:
        """Select a game and determine the action to perform."""
        selected = self.select(games, dynamic_collections, custom_collections, prompt=prompt)
        if selected is None:
            return (None, "cancel")

        secondary_key_pressed = False
        if isinstance(selected, tuple) and len(selected) == 2 and selected[1] in ("OPEN_ACTIONS", "SECONDARY_KEY"):
            selected, secondary_key_pressed = selected[0], True

        if isinstance(selected, str):
            return (selected, "nav")

        # Navigation payloads (collections, tags, create)
        if not isinstance(selected, Game):
            return (selected, "nav")

        should_open_action_menu = (
            (not self.quick_launch and not secondary_key_pressed) or
            (self.quick_launch and secondary_key_pressed)
        )

        if should_open_action_menu and self.enable_action_menu:
            action_result = self.select_game_action(selected, prompt=prompt) if prompt else self.select_game_action(selected)
            return (selected, action_result)

        return (selected, "launch")

    def resolve_game_icon(self, game: Game) -> str:
        """Resolve the icon specifier for a game (file path or theme icon name)."""
        # 1. Explicit icon path from game model (excluding cover art)
        if game.icon is not None:
            icon_path = Path(game.icon)
            if icon_path.is_file():
                return str(icon_path)

        source = game.source.lower().strip() if game.source else ""
        launcher = game.launcher.lower().strip() if game.launcher else ""
        appid = game.appid or ""

        # Derive target slug from appid or game.id
        target_slug = appid
        if not target_slug:
            for prefix in ("lutris_", "steam_", "heroic_", "filesystem_", "native_"):
                if game.id.startswith(prefix):
                    target_slug = game.id.removeprefix(prefix)
                    break
        if not target_slug:
            target_slug = game.id

        # 2. Steam icon lookup
        if source == "steam" or game.id.startswith("steam_"):
            steam_icon = self._find_steam_icon(target_slug)
            if steam_icon:
                return steam_icon
            return THEME_ICONS.get("steam", "steam")

        # 3. Lutris icon lookup (for Lutris source, Lutris ID, or Lutris launcher)
        if source == "lutris" or game.id.startswith("lutris_") or launcher == "lutris":
            lutris_icon = self._find_lutris_icon(target_slug, game_name=game.name)
            if lutris_icon:
                return lutris_icon
            return THEME_ICONS.get("lutris", "lutris")

        # Check if Lutris game icon exists on disk even if discovered via filesystem
        if target_slug or game.name:
            lutris_icon = self._find_lutris_icon(target_slug, game_name=game.name)
            if lutris_icon:
                return lutris_icon

        # 4. Local executable folder icon lookup for standalone / native games
        if game.executable is not None:
            local_icon = self._find_local_icon(Path(game.executable))
            if local_icon:
                return local_icon

        # 5. Desktop theme icon mapping by source FIRST, then launcher fallback
        if source in THEME_ICONS:
            return THEME_ICONS[source]

        if launcher in THEME_ICONS:
            return THEME_ICONS[launcher]

        # 6. Universal fallback icon
        return FALLBACK_ICON

    def _find_steam_icon(self, appid: str) -> str | None:
        """Find installed Steam icon on disk prioritizing SVG and high resolution PNGs."""
        home = Path.home()
        xdg_data = Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share"))

        candidates = [
            xdg_data / "icons" / "hicolor" / "scalable" / "apps" / f"steam_icon_{appid}.svg",
            xdg_data / "icons" / "hicolor" / "256x256" / "apps" / f"steam_icon_{appid}.png",
            xdg_data / "icons" / "hicolor" / "128x128" / "apps" / f"steam_icon_{appid}.png",
            home / ".local" / "share" / "icons" / "hicolor" / "128x128" / "apps" / f"steam_icon_{appid}.png",
            Path("/usr/share/icons/hicolor/128x128/apps") / f"steam_icon_{appid}.png",
            xdg_data / "Steam" / "appcache" / "librarycache" / appid / f"{appid}_icon.jpg",
            xdg_data / "Steam" / "appcache" / "librarycache" / appid / "icon.png",
            home / ".steam" / "steam" / "appcache" / "librarycache" / appid / f"{appid}_icon.jpg",
        ]
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
        return None

    def _find_lutris_icon(self, slug: str, game_name: str | None = None) -> str | None:
        """Find installed Lutris icon on disk prioritizing SVG and high resolution PNGs."""
        home = Path.home()
        xdg_data = Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share"))
        xdg_cache = Path(os.environ.get("XDG_CACHE_HOME", home / ".cache"))

        slugs = [slug]
        if "-" in slug:
            parts = slug.split("-")
            if parts[-1].isdigit():
                slugs.append("-".join(parts[:-1]))

        if game_name:
            clean_name = re.sub(r"[^\w\s-]", "", game_name.lower())
            slugified = re.sub(r"[\s_]+", "-", clean_name).strip("-")
            if slugified and slugified not in slugs:
                slugs.append(slugified)

        for s in slugs:
            if not s:
                continue
            candidates = [
                xdg_data / "icons" / "hicolor" / "scalable" / "apps" / f"lutris_{s}.svg",
                xdg_data / "icons" / "hicolor" / "128x128" / "apps" / f"lutris_{s}.png",
                home / ".local" / "share" / "icons" / "hicolor" / "128x128" / "apps" / f"lutris_{s}.png",
                xdg_data / "lutris" / "icons" / f"{s}.png",
                xdg_cache / "lutris" / "icons" / f"{s}.png",
            ]
            for candidate in candidates:
                if candidate.is_file():
                    return str(candidate)
        return None

    def _find_local_icon(self, executable: Path) -> str | None:
        """Find local game icon in the executable directory prioritizing SVG then PNG."""
        game_dir = executable.parent if executable.is_file() else executable
        if not game_dir.is_dir():
            return None

        candidates = [
            game_dir / "icon.svg",
            game_dir / "icon.png",
            game_dir / "icon.ico",
            game_dir / "app.png",
            game_dir / "app.ico",
        ]
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
        return None

    def show(self, games: list[Game]) -> Game | None:
        """Alias for select."""
        return self.select(games)


def show_menu(
    games: list[Game],
    prompt: str = "GameDeck > Library",
    theme: Path | str | None = None,
    theme_str: str | None = None,
    show_icons: bool = True,
) -> Game | None:
    """Display a Rofi game selection menu and return the chosen Game."""
    ui = RofiUI(
        prompt=prompt,
        theme=theme,
        theme_str=theme_str,
        show_icons=show_icons,
    )
    return ui.select(games)


def select_game(
    games: list[Game],
    prompt: str = "GameDeck > Library",
    theme: Path | str | None = None,
    theme_str: str | None = None,
    show_icons: bool = True,
) -> Game | None:
    """Convenience alias to show a Rofi game selection menu."""
    return show_menu(
        games=games,
        prompt=prompt,
        theme=theme,
        theme_str=theme_str,
        show_icons=show_icons,
    )
