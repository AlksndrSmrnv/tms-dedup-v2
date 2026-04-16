"""Базовые unit-тесты нормализации."""

from __future__ import annotations

from tools.test_duplicate_audit.normalize import (
    char_ngrams,
    fold,
    light_stem_ru,
    normalize_title,
    tokenize,
)


def test_fold_handles_yo_and_case() -> None:
    assert fold("Тёплый Ключ") == "теплыи ключ" or fold("Тёплый Ключ") == "теплый ключ"
    # стемминг не здесь — здесь только lower / ё→е / убрать пунктуацию
    folded = fold("Перевод по номеру телефона!")
    assert "!" not in folded
    assert folded == folded.lower()
    assert "ё" not in folded


def test_tokenize_splits_by_non_word() -> None:
    toks = tokenize("перевод по-номеру 1234 телефона")
    assert "перевод" in toks
    assert "телефона" in toks
    assert "1234" in toks  # цифры токенизируются


def test_light_stem_ru_shortens_long_ending() -> None:
    assert light_stem_ru("перевода") in {"перевод", "перевода"[:-1], "перевода"[:-2]}
    assert light_stem_ru("отправкой") != "отправкой"
    # короткие токены не трогаем
    assert light_stem_ru("sbp") == "sbp"
    assert light_stem_ru("ios") == "ios"


def test_normalize_title_removes_noise_words() -> None:
    _, tokens = normalize_title("Тест: Перевод по номеру телефона")
    # "тест" — noise
    assert all(not t.startswith("тест") for t in tokens)
    assert any("перевод" in t for t in tokens)


def test_char_ngrams_basic() -> None:
    ngr = char_ngrams("abc", n_min=2, n_max=3)
    assert " a" in ngr or "ab" in ngr
    assert any(len(g) == 3 for g in ngr)
