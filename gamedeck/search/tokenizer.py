"""Token generation for the GameDeck search engine.

This module is the single source of truth for all search token generation.
Both :class:`~gamedeck.search.index.SearchIndex` and :mod:`gamedeck.ui.rofi`
consume ``tokenize()`` so that search behaviour is identical across the
programmatic API and the interactive Rofi UI.
"""

from __future__ import annotations

import re
from pathlib import Path

__all__ = ["normalize", "tokenize", "ROMAN_TO_DIGIT", "STOP_WORDS", "TITLE_ALIASES"]

#: Roman numeral → Arabic digit mapping used for title normalisation.
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

#: Common English stop words excluded from acronym generation.
STOP_WORDS: frozenset[str] = frozenset(
    {"the", "a", "an", "of", "in", "and", "for", "to", "at", "by", "on"}
)

#: Curated title aliases for ambiguous acronyms (key = normalised title substring).
TITLE_ALIASES: dict[str, frozenset[str]] = {
    "hollow knight": frozenset({"hk"}),
    "grand theft auto v": frozenset({"gtav", "gta5", "gta v"}),
    "black myth  wukong": frozenset({"bmw", "black myth"}),
    "black myth wukong": frozenset({"bmw", "black myth"}),
    "elden ring": frozenset({"er"}),
    "counter strike 2": frozenset({"cs2", "cs 2"}),
    "counter strike": frozenset({"cs"}),
    "cyberpunk 2077": frozenset({"cp2077", "cyberpunk"}),
}

_PUNCT: re.Pattern[str] = re.compile(r"[^a-zA-Z0-9\s]+")


def normalize(text: str) -> str:
    """Lowercase and strip punctuation from *text*.

    Punctuation characters are replaced with spaces; the result is
    lowercased and stripped.

    Args:
        text: Raw input string.

    Returns:
        Cleaned, lowercase string with all punctuation replaced by spaces.

    Examples::

        >>> normalize("Counter-Strike 2")
        'counter strike 2'
        >>> normalize("Black Myth: Wukong")
        'black myth  wukong'
    """
    return _PUNCT.sub(" ", text).lower().strip()


def tokenize(
    name: str,
    appid: str | None = None,
    source: str | None = None,
    executable: Path | str | None = None,
    tags: list[str] | tuple[str, ...] | None = None,
    collections: list[str] | tuple[str, ...] | None = None,
    launcher: str | None = None,
) -> frozenset[str]:
    """Build the complete search token set for a single game.

    The token set is designed so that user queries such as abbreviations,
    compact forms, and partial words all find the correct game:

    - ``"bmw"`` → *Black Myth: Wukong* (acronym of significant words)
    - ``"gtav"`` / ``"gta5"`` → *Grand Theft Auto V* (acronym + roman digit)
    - ``"er"`` → *Elden Ring* (two-letter acronym)
    - ``"cs2"`` → *Counter-Strike 2* (acronym + version number)
    - ``"counterstrike2"`` → compact no-space form

    Tokens generated per game:

    1. Full normalised title (lower, punctuation stripped)
    2. Individual title words
    3. Compact no-space concatenation (``blackmythwukong``)
    4. Acronym of *all* initial letters (``bmw``)
    5. Acronym of *significant* (non-stop-word) initial letters when different
    6. Acronym + trailing version number (``gta5``, ``cs2``)
    7. Roman numeral → digit substitution tokens (``gta5`` from ``GTAV``)
    8. ``appid`` / slug variants (with and without separators)
    9. Provider ``source`` identifier
    10. Executable file stem (basename without extension)

    Args:
        name: Game display title.
        appid: Provider-specific app identifier or slug (e.g. Steam AppID,
            Lutris slug).
        source: Provider source name (e.g. ``"steam"``, ``"lutris"``).
        executable: Path to the game executable; only the stem is indexed.

    Returns:
        Immutable :class:`frozenset` of lowercase token strings.
    """
    tokens: set[str] = set()

    # 1. Clean words from title
    clean = normalize(name)
    words = [w for w in clean.split() if w]

    if not words:
        return frozenset({name.lower().strip()})

    # 2. Full normalised title string
    full_title = " ".join(words)
    tokens.add(full_title)

    # 3. Individual title words
    for w in words:
        tokens.add(w)

    # 4. Compact no-space concatenation (e.g. "blackmythwukong")
    tokens.add("".join(words))

    # 5. Acronyms — all initials and significant initials
    all_initials: list[str] = [w[0] for w in words if w[0].isalnum()]
    sig_initials: list[str] = [
        w[0] for w in words if w[0].isalnum() and w not in STOP_WORDS
    ]

    if all_initials:
        tokens.add("".join(all_initials))
    if sig_initials and sig_initials != all_initials:
        tokens.add("".join(sig_initials))

    # 6. Base acronym excluding trailing numbers / Roman numerals (e.g. "cs" from "CS 2", "gta" from "GTA V")
    leading_words = [w for w in words[:-1] if w not in STOP_WORDS and w[0].isalnum()]
    if len(words) > 1 and leading_words:
        tokens.add("".join(w[0] for w in leading_words))

    # 7. Acronym + trailing Arabic version number (e.g. "gta5" from "GTA 5", "cs2" from "CS 2")
    if len(words) > 1 and words[-1].isdigit():
        num = words[-1]
        base = "".join(
            w[0] for w in words[:-1]
            if w not in STOP_WORDS and w[0].isalnum()
        )
        if base:
            tokens.add(f"{base}{num}")

    # 8. Roman numeral → digit substitution (e.g. "V" → "5", "gtav" → "gta5")
    for idx, w in enumerate(words):
        if w in ROMAN_TO_DIGIT:
            digit = ROMAN_TO_DIGIT[w]
            tokens.add(digit)
            # Acronym with digit substitution for the last word
            if idx == len(words) - 1 and len(words) > 1:
                base = "".join(
                    p[0] for p in words[:-1]
                    if p not in STOP_WORDS and p[0].isalnum()
                )
                if base:
                    tokens.add(f"{base}{digit}")

    # 8. appid / slug variants
    if appid:
        slug = appid.lower().strip()
        if slug:
            tokens.add(slug)
            tokens.add(slug.replace("-", " ").replace("_", " ").strip())
            tokens.add(slug.replace("-", "").replace("_", ""))

    # 9. Source and Launcher identifiers
    if source:
        src = source.lower().strip()
        if src:
            tokens.add(src)
    if launcher:
        lnc = launcher.lower().strip()
        if lnc:
            tokens.add(lnc)

    # 10. Executable stem
    if executable is not None:
        stem = Path(executable).stem.lower().strip()
        if stem:
            tokens.add(stem)

    # 11. Assigned game tags & collections
    if tags:
        for t in tags:
            clean_tag = t.strip().lower()
            if clean_tag:
                tokens.add(clean_tag)
                tokens.add(clean_tag.replace("-", "").replace("_", ""))
                tokens.add(clean_tag.replace("-", " ").replace("_", " "))

    if collections:
        for c in collections:
            clean_coll = c.strip().lower()
            if clean_coll:
                tokens.add(clean_coll)
                tokens.add(clean_coll.replace("-", "").replace("_", ""))
                tokens.add(clean_coll.replace("-", " ").replace("_", " "))

    # 12. Curated alias tokens for well-known ambiguous titles
    collapsed_title = " ".join(clean.split())
    for alias_key, alias_tokens in TITLE_ALIASES.items():
        if alias_key in clean or alias_key in collapsed_title:
            tokens.update(alias_tokens)

    # Remove any empty strings that may have slipped in
    tokens.discard("")

    return frozenset(tokens)
