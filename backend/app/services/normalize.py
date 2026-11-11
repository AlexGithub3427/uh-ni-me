"""Text normalization shared by stored aliases and player input (F-003).

This is the only place names are turned into match keys. Aliases are stored
through it and player input goes through it, so any fold only has to be
consistent, not linguistically correct.
"""

import re
import unicodedata

# "ou" / "oo" (and longer runs) → "o"; "uu" → "u". Runs after macrons are
# stripped, so "Shōnen", "Shounen" and "Shonen" all end up the same.
_LONG_O = re.compile(r"o[ou]+")
_LONG_U = re.compile(r"u{2,}")


def _strip_latin_diacritics(char: str) -> str:
    """Drop the marks from an accented Latin letter (ō → o, é → e).

    Other scripts are left alone: decomposing kana would turn ガ into カ.
    """
    base = unicodedata.normalize("NFD", char)[0]
    return base if base.isascii() and base.isalpha() else char


def normalize(text: str) -> str:
    """Return the match key for a name.

    Lowercase, NFKC, fold macrons and long vowels, then remove everything that
    is not a letter or digit (punctuation, symbols and all whitespace).
    """
    text = unicodedata.normalize("NFKC", text).lower()
    # "HUNTER×HUNTER" is typed as "Hunter x Hunter"
    text = text.replace("×", "x")
    text = "".join(_strip_latin_diacritics(char) for char in text)
    # Fold before whitespace is removed so a vowel pair spanning two words
    # ("Naruto Uzumaki") is not treated as a long vowel.
    text = _LONG_O.sub("o", text)
    text = _LONG_U.sub("u", text)
    return "".join(char for char in text if char.isalnum())
