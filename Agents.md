# GameDeck - AI Development Guide

## Project Goal

GameDeck is a modern game launcher for Linux built primarily for Hyprland users.

It provides one unified launcher for:

- Steam
- Lutris
- Heroic Games Launcher
- Native Linux games
- Custom Windows games
- Emulators (future)

The launcher should feel similar to the HyDE launcher while remaining completely standalone.

---

## Design Goals

- Fast startup
- Clean architecture
- Modular providers
- Easy to extend
- Minimal dependencies
- Python 3.14

---

## Architecture

Providers never launch games.

Launchers never scan for games.

UI never scans providers directly.

Everything goes through ProviderManager.

```
Providers
      ↓
ProviderManager
      ↓
Launcher UI
      ↓
Launcher Backend
```

---

## Providers

Each provider returns:

```python
list[Game]
```

Providers:

- Steam
- Lutris
- Heroic
- Native
- Filesystem

---

## Launcher Backends

Launcher backends execute games.

Supported launch methods:

- Steam
- Lutris
- Native
- Wine
- Proton
- Bottles

---

## UI

Frontend:

Rofi

Future:

AGS

UI should never know where games came from.

---

## Coding Style

- pathlib only
- dataclasses
- type hints everywhere
- no global mutable state
- standard library preferred
- docstrings for public APIs
- small modules
- readable code over clever code

---

## Development Rules

Every commit must:

- Run successfully
- Keep the application functional
- Not break existing providers

Never generate placeholder implementations.

Prefer complete working implementations.

When adding a feature:

1. Implement
2. Test
3. Document
4. Commit

---

## Current Roadmap

Sprint 1

- Game model
- Steam provider
- Lutris provider
- Filesystem provider
- Provider manager

Sprint 2

- Rofi UI
- Launcher backend
- Search
- Icons

Sprint 3

- Heroic
- Native Linux
- Emulators

Sprint 4

- Cover art
- Favorites
- Recently played
- Settings
- Dusky integration