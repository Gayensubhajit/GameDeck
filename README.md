# GameDeck

<div align="center">

[![CI](https://github.com/Gayensubhajit/GameDeck/actions/workflows/ci.yml/badge.svg)](https://github.com/Gayensubhajit/GameDeck/actions/workflows/ci.yml)
[![Release](https://github.com/Gayensubhajit/GameDeck/actions/workflows/release.yml/badge.svg)](https://github.com/Gayensubhajit/GameDeck/actions/workflows/release.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12%20%7C%203.13-blue)](https://www.python.org/)
[![Version](https://img.shields.io/badge/version-0.5.0-informational)](https://github.com/Gayensubhajit/GameDeck/releases)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

**Universal, blazingly fast game launcher and library aggregator for Linux and Steam Deck.**  
One unified Rofi dmenu interface for Steam, Lutris, Heroic, Native Linux games, and custom Windows titles.

</div>

---

## Features

| Feature | Description |
|---|---|
| **< 10ms startup** | Reads directly from SQLite cache; Rofi never blocks on provider scans |
| **Unified search** | Acronym matching (`BMW` → *Black Myth: Wukong*, `ER` → *Elden Ring*, `CS2` → *Counter-Strike 2*) |
| **Collections** | Auto-collections (Favorites, Recent, per-provider) + custom named collections |
| **Tags** | Assign and filter by tags: RPG, Soulslike, FPS, Indie, Co-op, Finished, Wishlist, and custom |
| **Launch Profiles** | Multiple runner profiles per game (Proton-GE, Wine-Staging, Lutris, Steam) |
| **Background daemon** | `gamedeckd` watches provider directories for changes; rescans without restart |
| **SteamGridDB art** | Auto-downloads covers, icons, logos, hero banners in the background |
| **Backup & Restore** | Full JSON export/import of favorites, collections, tags, history, artwork, and profiles |
| **Edit Properties** | Override game title, launcher, executable, and all artwork paths via context menu |
| **No dependencies** | Pure Python standard library only (SQLite, TOML, threading) |

---

## Installation

### Option A — pip (editable install)
```bash
git clone https://github.com/Gayensubhajit/GameDeck.git
cd GameDeck
pip install -e .
```

### Option B — pipx (isolated install)
```bash
pipx install git+https://github.com/Gayensubhajit/GameDeck.git
```

### Enable the background daemon via Systemd
The daemon keeps the library cache fresh so the Rofi launcher starts instantly.

```bash
mkdir -p ~/.config/systemd/user
cp systemd/gamedeckd.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now gamedeckd.service
```

Verify it is running:
```bash
systemctl --user status gamedeckd.service
journalctl --user -u gamedeckd.service -f
```

---

## Usage

### Interactive Rofi Launcher

```bash
gamedeck
```

Rofi opens with your full library sorted by **Favorites → Recently Played → Alphabetical**. Dynamic collections (Favorites, Recently Played, per-provider) appear inline at the top of the menu; only non-empty collections are shown.

#### Keybindings

Bind GameDeck to a global shortcut in your window manager or desktop environment. Examples (not hardcoded — adapt to your setup):

```
SUPER + ALT + G       # Open GameDeck
SUPER + CTRL + G      # Open GameDeck
SUPER + SHIFT + ALT + G
```

| Key | Action |
|---|---|
| Type to search | Live fuzzy + acronym search across all games |
| `Enter` | Open the Game Actions menu for the selected game (default) |
| `Alt+Return` | Quick launch game immediately (or configured via `secondary_action_key`) |
| `Escape` | Go back / close |
| Arrow keys | Navigate list |

#### Quick Launch Mode vs Default Mode

By default (`quick_launch = false`), pressing `Enter` on a game opens its **Game Actions menu**. If you want `Enter` to launch games immediately (Quick Launch mode), set `quick_launch = true` in `~/.config/gamedeck/config.toml`:

```toml
[ui]
quick_launch = false                 # false (default): Enter opens Action Menu; true: Enter launches directly
secondary_action_key = "Alt+Return"   # Keybinding to trigger alternative action
```

#### Rofi Navigation

The main library menu features clean submenus at the top: **📁 Collections...** and **🏷 Filter by Tag...**, followed by your full game library (Favorites → Recently Played → Alphabetical).
- **📁 Collections...** opens the dedicated Collections submenu (Steam, Lutris, Heroic, custom collections, and Create Collection).
- **🏷 Filter by Tag...** opens the Tag selection submenu.

#### Game Context Menu

Selecting a game opens the Game Actions menu (with **▶ Play** pre-selected):

| Option | Description |
|---|---|
| ▶ Play | Launch the game |
| ⭐ Favorite / Unfavorite | Pin/unpin from top of library |
| 📂 Open Folder | Open install directory (when executable exists) |
| ⚙ Configure | Open Lutris configuration (Lutris games only) |
| 🍷 Browse Prefix | Open Wine prefix (Lutris/Wine games) |
| 🏷 Edit Tags | Add or remove tags for this game |
| 📁 Manage Collections | Add the game to a custom collection |
| 📝 Properties | View full metadata summary |
| ✏ Edit Properties | Override title, launcher, artwork paths |
| 🔄 Refresh Metadata | Re-fetch artwork and metadata cache |
| ← Back | Return to the library |

---

## CLI Reference

| Command | Description |
|---|---|
| `gamedeck` | Open interactive Rofi launcher |
| `gamedeck --list` | Print all games (name, source, launcher, stats) |
| `gamedeck --fav "BMW"` | Toggle favorite on Black Myth: Wukong |
| `gamedeck --details "Elden Ring"` | Show full metadata for a game |
| `gamedeck --collections` | List all collections with counts |
| `gamedeck --collection Favorites` | Open Rofi filtered to a collection |
| `gamedeck --import-categories` | Import Steam/Lutris/Heroic categories as Collections |
| `gamedeck --backup` | Export state to `gamedeck_backup.json` |
| `gamedeck --backup ~/backups/my.json` | Export state to a specific path |
| `gamedeck --restore ~/backups/my.json` | Restore from a backup JSON file |
| `gamedeckd --sync` | Force immediate library scan and cache update |
| `gamedeckd --verbose` | Start daemon with debug logging |

### Log Level Control

Set `GAMEDECK_LOG_LEVEL` to control verbosity:

```bash
GAMEDECK_LOG_LEVEL=DEBUG gamedeck
```

Valid values: `DEBUG`, `INFO` (default), `WARNING`, `ERROR`, `CRITICAL`.

---

## Configuration

GameDeck reads settings from `~/.config/gamedeck/config.toml`.  
A default config is created on first run if none exists.

```toml
[providers]
steam    = true
lutris   = true
heroic   = true
native   = true
filesystem = false

[filesystem]
# Custom directories to scan for .desktop or .exe files
search_dirs = ["~/Games", "~/Applications"]

[ui]
recent_games_limit = 5
show_icons         = true
rofi_theme         = ""          # Path to a custom Rofi theme (.rasi)
secondary_action_key = "Alt+Return"   # Opens action menu; Enter launches directly

[steamgriddb]
api_key = ""                     # Optional: SteamGridDB API key for artwork downloads
```

---

## Collections

GameDeck provides two types of collections:

**Auto-collections** (always up to date; empty collections are hidden):
- **Favorites** — all starred games
- **Recent** — last played games  
- **Steam / Lutris / Heroic / Native / Filesystem** — per-provider views

Collections appear inline at the top of the Rofi library menu. Only collections with at least one game are shown.

**Custom collections** (user-created, persist in SQLite):
```bash
# Via Rofi → ➕ Create Collection... or Manage Collections in the action menu
# Via context menu on any game → 📁 Manage Collections
```

### Importing from Providers

Import existing Steam categories, Lutris categories, and Heroic lists as GameDeck Collections:

```bash
gamedeck --import-categories
```

Duplicates are automatically skipped. Run again after adding new categories.

---

## Tags

Supported built-in tags: `RPG`, `Soulslike`, `FPS`, `Indie`, `Co-op`, `Finished`, `Wishlist`

Tags can be assigned via the context menu → **🏷 Edit Tags**, and are filterable via **🏷 Filter by Tag...** in the main Rofi menu. Only tags with at least one assigned game appear in the filter list. Custom tags can be created by typing a new name.

---

## Launch Profiles

Each game can have multiple named launch profiles — useful for switching between runner versions:

```
Black Myth: Wukong
├── Lutris (default)
├── Proton Experimental
├── GE-Proton8
└── Wine-Staging
```

Switch profiles via the game action menu (**Alt+Return** → **⚡ Launch Profiles**). The selected profile persists across sessions.

---

## Backup & Restore

Export your entire GameDeck state to a portable JSON file:

```bash
gamedeck --backup ~/gamedeck_backup.json
```

This captures:
- Favorites
- Custom collections and memberships
- Tags and game tag assignments
- Game property overrides (title, launcher, artwork)
- Recent play history and launch counts
- Launch profiles
- SQLite table snapshots
- Settings snapshot

Restore on a new machine or after a reinstall:

```bash
gamedeck --restore ~/gamedeck_backup.json
```

Restore is safe to re-apply — uses `INSERT OR REPLACE` semantics.

---

## Architecture

```
Providers                     ← Steam, Lutris, Heroic, Native, Filesystem
     ↓
ProviderManager               ← Aggregates, deduplicates, fingerprints
     ↓
Scanner + MetadataManager     ← SQLite enrichment, artwork resolution
     ↓
SearchIndex                   ← In-memory ranked search, warmed by gamedeckd
     ↓
RofiUI                        ← dmenu frontend, context menus
     ↓
Launchers                     ← Steam, Lutris, Native, Wine/Proton backends
```

**Design principles** (from `Agents.md`):
- Providers never launch games
- Launchers never scan for games
- UI never calls providers directly
- Everything routes through `ProviderManager`
- No global mutable state
- `pathlib` only, no `os.path`
- Standard library only; no third-party runtime dependencies

---

## Development & Testing

```bash
# Run the full test suite (206 tests)
python3 -m unittest discover -s tests -v

# With coverage
coverage run -m unittest discover -s tests -v
coverage report -m

# Lint / format
flake8 gamedeck tests
black gamedeck tests
mypy gamedeck
```

---

## Contributing

1. Fork the repo and create a feature branch
2. Follow the coding style in `Agents.md`
3. Add tests for all new functionality
4. Ensure `python3 -m unittest discover -s tests` passes with zero failures
5. Open a PR against `main`

---

## License

This project is licensed under the [MIT License](LICENSE).
