"""Rofi frontend user interface for GameDeck."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from gamedeck.models import Game

__all__ = ["RofiUI", "show_menu", "select_game", "generate_search_metadata"]

logger = logging.getLogger(__name__)

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

# Roman numerals to digits mapping for title normalization
ROMAN_TO_DIGIT: dict[str, str] = {
    "i": "1",
    "ii": "2",
    "iii": "3",
    "iv": "4",
    "v": "5",
    "vi": "6",
    "vii": "7",
    "viii": "8",
    "ix": "9",
    "x": "10",
}


def generate_search_metadata(name: str, appid: str | None = None, source: str | None = None) -> str:
    """Generate search keywords including abbreviations, compact forms, and normalized tokens.

    Enables matching abbreviations (e.g. 'bmw' -> 'Black Myth Wukong', 'cs2' -> 'Counter-Strike 2'),
    missing spaces (e.g. 'blackmyth', 'cyberpunk2077'), and punctuation variations.

    Args:
        name: Display title of the game.
        appid: Optional provider-specific app ID or slug.
        source: Optional provider source identifier.

    Returns:
        Space-separated search keywords string for Rofi metadata indexing.
    """
    tokens: set[str] = set()

    # 1. Clean words without punctuation
    clean_name = re.sub(r"[^a-zA-Z0-9\s]+", " ", name)
    words = [w.lower().strip() for w in clean_name.split() if w.strip()]

    if not words:
        return name.lower().strip()

    # 2. Add individual word tokens
    for w in words:
        tokens.add(w)

    # 3. Add normalized space-separated and space-free compact strings
    tokens.add(" ".join(words))
    tokens.add("".join(words))  # missing spaces (e.g. blackmythwukong)

    # 4. Generate acronyms / abbreviations (e.g. bmw, cs, gta, cp)
    stop_words = {"the", "a", "an", "of", "in", "and", "for", "to", "at", "by", "on"}
    all_initials: list[str] = []
    significant_initials: list[str] = []

    for w in words:
        if w[0].isalnum():
            all_initials.append(w[0])
            if w not in stop_words:
                significant_initials.append(w[0])

    if all_initials:
        tokens.add("".join(all_initials))
    if significant_initials:
        tokens.add("".join(significant_initials))

    # Append trailing number/version to acronym (e.g. GTA 5 -> gta5, CS 2 -> cs2, TW 3 -> tw3)
    if len(words) > 1 and words[-1].isdigit():
        num = words[-1]
        base_acronym = "".join([w[0] for w in words[:-1] if w not in stop_words])
        if base_acronym:
            tokens.add(f"{base_acronym}{num}")

    # Map Roman numerals to digits in compact and acronym tokens (e.g. GTA V -> gta5)
    for idx, w in enumerate(words):
        if w in ROMAN_TO_DIGIT:
            digit = ROMAN_TO_DIGIT[w]
            tokens.add(digit)
            # Acronym with digit substitution
            if idx == len(words) - 1 and len(words) > 1:
                base_acronym = "".join([part[0] for part in words[:-1] if part not in stop_words])
                if base_acronym:
                    tokens.add(f"{base_acronym}{digit}")

    # 5. Include appid and slug if present
    if appid:
        clean_appid = appid.lower().strip()
        tokens.add(clean_appid)
        tokens.add(clean_appid.replace("-", " ").replace("_", " "))
        tokens.add(clean_appid.replace("-", "").replace("_", ""))

    if source:
        tokens.add(source.lower().strip())

    return " ".join(sorted(tokens))


@dataclass(slots=True)
class RofiUI:
    """Rofi dmenu-based graphical launcher interface for selecting games.

    Presents a searchable, interactive menu of games with favorite star indicators (★),
    interactive action cards, fuzzy matching, abbreviation indexing, and fast startup.

    Attributes:
        prompt: Display prompt text shown in the Rofi search bar.
        theme: Optional path to a custom Rofi .rasi theme file.
        theme_str: Optional inline .rasi theme string to customize styling.
        show_icons: Whether to enable and send icon paths/names to Rofi.
        case_insensitive: Whether search matching should be case-insensitive.
        matching: Rofi matching algorithm (fuzzy, normal, regex, glob).
        sorting_method: Rofi sorting algorithm (fzf, normal).
        enable_action_menu: Whether selecting a game prompts Play / Favorite / Back.
        rofi_bin: Name or absolute path of the Rofi executable.
    """

    prompt: str = "GameDeck"
    theme: Path | str | None = None
    theme_str: str | None = None
    show_icons: bool = True
    case_insensitive: bool = True
    matching: str = "fuzzy"
    sorting_method: str = "fzf"
    enable_action_menu: bool = True
    rofi_bin: str = "rofi"

    def select(self, games: list[Game]) -> Game | None:
        """Display the list of games in Rofi and return the user's selected Game.

        Args:
            games: List of Game model instances to present.

        Returns:
            The selected Game model instance, or None if cancelled.
        """
        if not games:
            return None

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
            self.prompt,
            "-format",
            "i",
            "-no-custom",
            "-matching",
            self.matching,
            "-sort",
            "-sorting-method",
            self.sorting_method,
        ]

        if self.case_insensitive:
            cmd.append("-i")

        if self.show_icons:
            cmd.append("-show-icons")

        if self.theme is not None:
            cmd.extend(["-theme", str(self.theme)])

        if self.theme_str is not None and self.theme_str.strip():
            cmd.extend(["-theme-str", self.theme_str.strip()])

        lines: list[str] = []
        name_map: dict[str, Game] = {}

        for idx, game in enumerate(games):
            base_title = game.name.strip() if game.name else f"Game #{idx + 1}"
            # Render star indicator for favorites
            display_title = f"★  {base_title}" if game.favorite else base_title
            name_map[display_title] = game

            # Generate search metadata
            meta_keywords = generate_search_metadata(
                name=game.name,
                appid=game.appid,
                source=game.source,
            )

            icon_spec = self.resolve_game_icon(game) if self.show_icons else None

            parts = [display_title, f"meta\x1f{meta_keywords}", f"info\x1f{idx}"]
            if icon_spec:
                parts.insert(1, f"icon\x1f{icon_spec}")

            line = f"{parts[0]}\0{'\x1f'.join(parts[1:])}"
            lines.append(line)

        input_payload = "\n".join(lines) + "\n"
        logger.debug("Opening Rofi menu with %d items", len(games))

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

        if result.returncode != 0:
            logger.debug("Rofi selection cancelled (returncode=%d)", result.returncode)
            return None

        output = result.stdout.strip()
        if not output:
            return None

        # Parse selected index
        if output.isdigit():
            selected_idx = int(output)
            if 0 <= selected_idx < len(games):
                selected = games[selected_idx]
                logger.info("User selected game: %s [%s]", selected.name, selected.id)
                return selected

        # Fallback to display title matching
        selected = name_map.get(output)
        if selected is not None:
            logger.info("User selected game (title match): %s [%s]", selected.name, selected.id)
        return selected

    def select_game_action(self, game: Game) -> str:
        """Display an action dialog for the chosen game (Play, Toggle Favorite, or Back).

        Args:
            game: Selected Game instance.

        Returns:
            One of 'launch', 'toggle_favorite', or 'back'.
        """
        executable = shutil.which(self.rofi_bin)
        if executable is None:
            return "launch"

        fav_label = "★  Remove from Favorites" if game.favorite else "★  Add to Favorites"
        items = [
            f"▶  Play {game.name}",
            fav_label,
            "⬅  Back to Library",
        ]

        cmd: list[str] = [
            executable,
            "-dmenu",
            "-p",
            game.name,
            "-format",
            "i",
            "-no-custom",
            "-matching",
            "fuzzy",
        ]

        if self.case_insensitive:
            cmd.append("-i")

        if self.theme is not None:
            cmd.extend(["-theme", str(self.theme)])

        if self.theme_str is not None and self.theme_str.strip():
            cmd.extend(["-theme-str", self.theme_str.strip()])

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
            logger.error("Failed to execute action menu: %s", err)
            return "launch"

        if result.returncode != 0:
            return "back"

        output = result.stdout.strip()
        if output == "0":
            return "launch"
        elif output == "1":
            return "toggle_favorite"
        else:
            return "back"

    def select_with_action(self, games: list[Game]) -> tuple[Game | None, str]:
        """Select a game and determine action (launch, toggle_favorite, or cancel).

        Args:
            games: List of games to present.

        Returns:
            Tuple of (selected_game, action_name).
        """
        selected_game = self.select(games)
        if selected_game is None:
            return (None, "cancel")

        if not self.enable_action_menu:
            return (selected_game, "launch")

        action = self.select_game_action(selected_game)
        return (selected_game, action)

    def resolve_game_icon(self, game: Game) -> str:
        """Resolve the icon specifier for a game (file path or theme icon name).

        Evaluation hierarchy:
            1. Dedicated game.icon path if existing.
            2. Steam application icon.
            3. Lutris application icon.
            4. Local desktop / executable icon.
            5. Desktop theme icon (steam, lutris, wine, heroic).
            6. Fallback desktop icon (applications-games).

        Explicitly excludes cover art.

        Args:
            game: Game model instance.

        Returns:
            String representing a file path or desktop theme icon name.
        """
        # 1. Explicit icon path from game model (excluding cover art)
        if game.icon is not None:
            icon_path = Path(game.icon)
            if icon_path.is_file():
                return str(icon_path)

        source = game.source.lower().strip() if game.source else ""
        launcher = game.launcher.lower().strip() if game.launcher else ""
        appid = game.appid or ""

        # 2. Steam icon lookup
        if source == "steam" and appid:
            steam_icon = self._find_steam_icon(appid)
            if steam_icon:
                return steam_icon
            return THEME_ICONS.get("steam", "steam")

        # 3. Lutris icon lookup
        if source == "lutris" and appid:
            lutris_icon = self._find_lutris_icon(appid)
            if lutris_icon:
                return lutris_icon
            return THEME_ICONS.get("lutris", "lutris")

        # 4. Local executable folder icon lookup for standalone / native games
        if game.executable is not None:
            local_icon = self._find_local_icon(Path(game.executable))
            if local_icon:
                return local_icon

        # 5. Desktop theme icon mapping by source or launcher
        if launcher in THEME_ICONS:
            return THEME_ICONS[launcher]

        if source in THEME_ICONS:
            return THEME_ICONS[source]

        # 6. Universal fallback icon
        return FALLBACK_ICON

    def _find_steam_icon(self, appid: str) -> str | None:
        """Find installed Steam icon on disk without deep recursion."""
        home = Path.home()
        xdg_data = Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share"))

        candidates = [
            xdg_data / "icons" / "hicolor" / "128x128" / "apps" / f"steam_icon_{appid}.png",
            xdg_data / "icons" / "hicolor" / "256x256" / "apps" / f"steam_icon_{appid}.png",
            xdg_data / "icons" / "hicolor" / "scalable" / "apps" / f"steam_icon_{appid}.svg",
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

    def _find_lutris_icon(self, slug: str) -> str | None:
        """Find installed Lutris icon on disk without deep recursion."""
        home = Path.home()
        xdg_data = Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share"))
        xdg_cache = Path(os.environ.get("XDG_CACHE_HOME", home / ".cache"))

        candidates = [
            xdg_data / "icons" / "hicolor" / "128x128" / "apps" / f"lutris_{slug}.png",
            xdg_data / "icons" / "hicolor" / "scalable" / "apps" / f"lutris_{slug}.svg",
            home / ".local" / "share" / "icons" / "hicolor" / "128x128" / "apps" / f"lutris_{slug}.png",
            xdg_data / "lutris" / "icons" / f"{slug}.png",
            xdg_cache / "lutris" / "icons" / f"{slug}.png",
        ]
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
        return None

    def _find_local_icon(self, executable: Path) -> str | None:
        """Find local game icon in the executable directory."""
        game_dir = executable.parent if executable.is_file() else executable
        if not game_dir.is_dir():
            return None

        candidates = [
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
    prompt: str = "GameDeck",
    theme: Path | str | None = None,
    theme_str: str | None = None,
    show_icons: bool = True,
) -> Game | None:
    """Display a Rofi game selection menu and return the chosen Game.

    Args:
        games: List of Game instances to present in the menu.
        prompt: Title or prompt text to display.
        theme: Optional path to a custom .rasi theme file.
        theme_str: Optional inline .rasi theme string.
        show_icons: Whether to render game cover/icon graphics.

    Returns:
        The selected Game instance, or None if dismissed.
    """
    ui = RofiUI(
        prompt=prompt,
        theme=theme,
        theme_str=theme_str,
        show_icons=show_icons,
    )
    return ui.select(games)


def select_game(
    games: list[Game],
    prompt: str = "GameDeck",
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
