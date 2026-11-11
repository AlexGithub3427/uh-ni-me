"""F-003: the one normalization function used for aliases and player input."""

import pytest

from app.services.normalize import normalize

# (raw title variant, expected match key)
TITLE_VARIANTS: list[tuple[str, str]] = [
    # macrons and long vowels all fold to the short vowel
    ("Shōnen", "shonen"),
    ("Shounen", "shonen"),
    ("Shonen", "shonen"),
    ("Yū Yū Hakusho", "yuyuhakusho"),
    ("Yuu Yuu Hakusho", "yuyuhakusho"),
    ("Yu Yu Hakusho", "yuyuhakusho"),
    ("Bungō Stray Dogs", "bungostraydogs"),
    ("Bungou Stray Dogs", "bungostraydogs"),
    ("Tōkyō Ghoul", "tokyoghol"),
    ("Tokyo Ghoul", "tokyoghol"),
    ("Ōkami to Kōshinryō", "okamitokoshinryo"),
    ("Ookami to Koushinryou", "okamitokoshinryo"),
    ("JoJo no Kimyou na Bouken", "jojonokimyonaboken"),
    (
        "Kaguya-sama wa Kokurasetai: Tensai-tachi no Renai Zunousen",
        "kaguyasamawakokurasetaitensaitachinorenaizunosen",
    ),
    # the fold is uniform, so English words containing "ou" / "oo" change too
    ("Your Name", "yorname"),
    ("Your Name.", "yorname"),
    ("Soul Eater", "soleater"),
    ("Mob Psycho 100", "mobpsycho100"),
    ("Code Geass: Hangyaku no Lelouch", "codegeasshangyakunoleloch"),
    ("Boogiepop wa Warawanai", "bogiepopwawarawanai"),
    ("Fullmetal Alchemist: Brotherhood", "fullmetalalchemistbrotherhod"),
    # romaji vs English stay distinct keys (they are separate aliases)
    ("Shingeki no Kyojin", "shingekinokyojin"),
    ("Attack on Titan", "attackontitan"),
    # punctuation, symbols and whitespace
    ("Hunter x Hunter", "hunterxhunter"),
    ("HUNTER×HUNTER", "hunterxhunter"),
    ("Re:Zero kara Hajimeru Isekai Seikatsu", "rezerokarahajimeruisekaiseikatsu"),
    ("Re:ZERO -Starting Life in Another World-", "rezerostartinglifeinanotherworld"),
    ("K-On!", "kon"),
    ("Steins;Gate", "steinsgate"),
    ("  Cowboy \t Bebop\n", "cowboybebop"),
    # NFKC: full-width and half-width forms
    ("ＮＡＲＵＴＯ", "naruto"),
    ("ｶﾞﾝﾀﾞﾑ", "ガンダム"),
    # other Latin diacritics
    ("Pokémon", "pokemon"),
    # native titles survive, voiced kana keep their marks
    ("進撃の巨人", "進撃の巨人"),
    ("機動戦士ガンダム", "機動戦士ガンダム"),
]


@pytest.mark.parametrize(("raw", "expected"), TITLE_VARIANTS)
def test_f003_normalizes_title_variant(raw: str, expected: str) -> None:
    assert normalize(raw) == expected


def test_f003_lowercases() -> None:
    assert normalize("NARUTO") == normalize("naruto") == "naruto"


def test_f003_applies_nfkc() -> None:
    assert normalize("Ｆａｔｅ／Ｚｅｒｏ") == "fatezero"


def test_f003_strips_punctuation_and_whitespace() -> None:
    assert normalize("  Dr. STONE:  New_World!? ") == "drstonenewworld"


def test_f003_folds_macrons() -> None:
    assert normalize("Shōnen") == normalize("Shounen") == normalize("Shonen") == "shonen"


def test_f003_folds_long_vowels_in_english_words() -> None:
    assert normalize("your") == "yor"


def test_f003_does_not_fold_across_word_boundaries() -> None:
    # "Naruto Uzumaki" must not become "narutozumaki"
    assert normalize("Naruto Uzumaki") == "narutouzumaki"


def test_f003_punctuation_only_input_is_empty() -> None:
    assert normalize(" !?… ") == ""


@pytest.mark.parametrize("raw", [raw for raw, _ in TITLE_VARIANTS])
def test_f003_is_idempotent(raw: str) -> None:
    once = normalize(raw)
    assert normalize(once) == once
