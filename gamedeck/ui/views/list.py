"""ListViewRenderer: Classic fast, high-density list presentation for GameDeck.

Renders library games as a linear list with favorite indicators (★), rich metadata,
submenus for collections/tags/stats, and custom keybindings for switching views.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gamedeck.models import Game
from gamedeck.search.tokenizer import tokenize as _search_tokenize

logger = logging.getLogger(__name__)

STATUS_BAR_TEXT: str = (
    "<b>Enter</b> Play  •  <b>Alt</b> Options  •  "
    "<b>Ctrl+1</b> List  •  <b>Ctrl+2</b> Grid  •  "
    "<b>Ctrl+F</b> Search  •  <b>Esc</b> Back  •  <b>F5</b> Refresh"
)


def _calc_rofi_lines(count: int, max_lines: int = 12) -> str:
    """Calculate dynamic -lines argument for Rofi to eliminate empty vertical space."""
    return str(min(max(count, 1), max_lines))


@dataclass(slots=True)
class ListViewRenderer:
    """Renders library games in high-density linear list format."""

    rofi_bin: str = "rofi"
    show_icons: bool = True
    case_insensitive: bool = True
    matching: str = "fuzzy"
    sorting_method: str = "fzf"
    secondary_action_key: str = "Alt+Return"

    def render(
        self,
        games: list[Game],
        prompt: str = "GameDeck > Library",
        theme_path: Path | str | None = None,
        theme_str: str | None = None,
        resolve_icon_fn: Any = None,
    ) -> tuple[Game | Any | None, int, str]:
        """Display games in classic list view.

        Returns:
            (selected_item, return_code, action_trigger)
        """
        if not games:
            return (None, 1, "cancel")

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

        # Top navigation submenus
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

            # Build rich search tokens
            tags = getattr(game, "tags", None)
            collections = getattr(game, "collections", None)
            tokens = set(_search_tokenize(
                name=game.name,
                appid=game.appid,
                source=game.source,
                launcher=game.launcher,
                executable=game.executable,
                tags=tags,
                collections=collections,
            ))
            if game.favorite:
                tokens.update(["favorite", "favorites", "star", "starred"])
            if game.installed:
                tokens.add("installed")
            meta_keywords = " ".join(sorted(tokens))

            icon_spec = resolve_icon_fn(game) if (resolve_icon_fn and self.show_icons) else None

            parts = [display_title, f"meta\x1f{meta_keywords}", f"info\x1fgame:{idx}"]
            if icon_spec:
                parts.insert(1, f"icon\x1f{icon_spec}")

            lines.append(f"{parts[0]}\0{'\x1f'.join(parts[1:])}")

        executable = shutil.which(self.rofi_bin)
        if executable is None:
            raise RuntimeError(f"Rofi executable '{self.rofi_bin}' was not found in PATH.")

        cmd: list[str] = [
            executable,
            "-dmenu",
            "-p",
            prompt,
            "-format",
            "i",
            "-matching",
            self.matching,
            "-sort",
            "-sorting-method",
            self.sorting_method,
            "-lines",
            _calc_rofi_lines(len(lines)),
            "-kb-custom-1",
            self.secondary_action_key,
            "-kb-custom-2",
            "Control+1",
            "-kb-custom-3",
            "Control+2",
            "-kb-custom-4",
            "Control+f",
            "-kb-custom-5",
            "F5",
            "-mesg",
            STATUS_BAR_TEXT,
        ]

        if self.case_insensitive:
            cmd.append("-i")
        if self.show_icons:
            cmd.append("-show-icons")
        if theme_path is not None:
            cmd.extend(["-theme", str(theme_path)])
        if theme_str is not None and theme_str.strip():
            cmd.extend(["-theme-str", theme_str.strip()])

        cmd.extend(["-theme-str", 'entry { placeholder: "Type to search..."; }'])

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
        except OSError as err:
            logger.error("Failed to execute Rofi list process: %s", err)
            raise RuntimeError(f"Failed to execute Rofi list: {err}") from err

        ret_code = result.returncode
        output = result.stdout.strip()

        # Keyboard shortcuts
        if ret_code == 11:
            return (None, 11, "switch_view_list")
        elif ret_code == 12:
            return (None, 12, "switch_view_grid")
        elif ret_code == 14:
            return (None, 14, "refresh")
        elif ret_code not in (0, 10):
            return (None, ret_code, "cancel")

        if not output:
            return (None, ret_code, "cancel")

        open_actions = (ret_code == 10)
        action_trigger = "action_menu" if open_actions else "launch"

        if output.isdigit():
            selected_idx = int(output)
            if 0 <= selected_idx < nav_count:
                nav_payload = nav_by_index[selected_idx]
                if open_actions:
                    return (None, ret_code, "cancel")
                return (nav_payload, ret_code, "nav")

            game_idx = selected_idx - nav_count
            if 0 <= game_idx < len(games):
                selected = games[game_idx]
                return (selected, ret_code, action_trigger)

        selected = name_map.get(output)
        if selected is not None:
            return (selected, ret_code, action_trigger)

        return (None, ret_code, "cancel")
