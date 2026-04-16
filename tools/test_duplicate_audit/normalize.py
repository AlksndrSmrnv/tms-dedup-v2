"""Нормализация текста для русского + латиницы.

Принципы:
- без тяжёлых морфологических пакетов (pymorphy и т.п.);
- достаточная для title и section name «лёгкая» нормализация:
  * lowercase, ё→е, NFKC,
  * удаление пунктуации,
  * схлопывание пробелов,
  * удаление noise-words (тест/проверка/кейс),
  * удаление стоп-слов,
  * эвристический стемминг русских окончаний,
- char-ngrams для сравнения «на глаз похожих» слов.

Реализация стемминга — короткое правило отсечения типичных флексий.
Не претендует на лингвистическую точность, но стабильна для нужд
поиска дублей коротких названий.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from .config import NOISE_WORDS, STOPWORDS

# --------------------------------------------------------------------------- #
# Базовые регулярные выражения (предкомпилированы)
# --------------------------------------------------------------------------- #

_PUNCT_RE = re.compile(r"[^\w\s-]", flags=re.UNICODE)
_MULTI_SPACE_RE = re.compile(r"\s+", flags=re.UNICODE)
_NON_TOKEN_RE = re.compile(r"[^\wа-яё]+", flags=re.IGNORECASE | re.UNICODE)

# Окончания, отсекаемые при эвристическом стемминге (порядок важен — длинные раньше).
# Словарик подобран под сниппеты TMS/банковских тестов, а не под полноценную
# морфологию: цель — уменьшить вариативность словоформ.
_RU_ENDINGS: tuple[str, ...] = (
    "ированием",
    "ирования",
    "ированная",
    "ированному",
    "ированные",
    "ированный",
    "ировать",
    "ированы",
    "ирован",
    "иваем",
    "ируем",
    "ируешь",
    "овании",
    "ованию",
    "ованием",
    "ование",
    "ованный",
    "ованная",
    "ованные",
    "ованных",
    "ованного",
    "ованным",
    "ованы",
    "ую",
    "юю",
    "ая",
    "яя",
    "ое",
    "ее",
    "ых",
    "их",
    "ым",
    "им",
    "ого",
    "его",
    "ому",
    "ему",
    "ыми",
    "ими",
    "ами",
    "ями",
    "ей",
    "ой",
    "ою",
    "ею",
    "ий",
    "ый",
    "ие",
    "ые",
    "ов",
    "ев",
    "ам",
    "ям",
    "ах",
    "ях",
    "ов",
    "ев",
    "ы",
    "и",
    "а",
    "я",
    "о",
    "е",
    "у",
    "ю",
    "ь",
)


def _nfkc(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def collapse_whitespace(text: str) -> str:
    return _MULTI_SPACE_RE.sub(" ", text).strip()


def strip_punct(text: str) -> str:
    return _PUNCT_RE.sub(" ", text)


def fold(text: str) -> str:
    """Базовый fold: NFKC → lower → ё→е → collapse whitespace."""
    if not text:
        return ""
    text = _nfkc(text).lower().replace("ё", "е")
    text = strip_punct(text)
    text = collapse_whitespace(text)
    return text


# --------------------------------------------------------------------------- #
# Токенизация и стемминг
# --------------------------------------------------------------------------- #


def tokenize(text: str) -> list[str]:
    """Разбить нормализованный текст на токены.

    Ожидается, что text уже прошёл `fold()`. Но функция устойчива и
    к raw-строке — применит `fold()` сама.
    """
    if not text:
        return []
    if re.search(r"[A-ZА-ЯЁ]", text) or _PUNCT_RE.search(text):
        text = fold(text)
    return [t for t in _NON_TOKEN_RE.split(text) if t]


def light_stem_ru(token: str) -> str:
    """Эвристический стемминг: отсекает длинное русское окончание.

    Латинские токены, цифры, короткие (≤3 символов) — не трогаем,
    чтобы не ломать ключевые слова вроде `sbp`, `qr`, `ios`, `web`.
    """
    if len(token) <= 3:
        return token
    if not any("а" <= ch <= "я" for ch in token):
        return token  # не русское слово
    for ending in _RU_ENDINGS:
        if len(token) - len(ending) >= 3 and token.endswith(ending):
            return token[: -len(ending)]
    return token


def is_noise(token: str) -> bool:
    return token in NOISE_WORDS


def is_stopword(token: str) -> bool:
    return token in STOPWORDS


def normalize_tokens(tokens: Iterable[str], *, keep_stopwords: bool = False) -> list[str]:
    """Применить стемминг + фильтр noise/stopwords."""
    result: list[str] = []
    for raw in tokens:
        if not raw:
            continue
        if is_noise(raw):
            continue
        if not keep_stopwords and is_stopword(raw):
            continue
        stem = light_stem_ru(raw)
        if not stem:
            continue
        result.append(stem)
    return result


def normalize_title(title: str) -> tuple[str, list[str]]:
    """Вернуть (нормализованный title-строка, список токенов).

    Строка удобна для TF-IDF, токены — для overlap-проверок.
    """
    folded = fold(title)
    raw_tokens = tokenize(folded)
    tokens = normalize_tokens(raw_tokens)
    return " ".join(tokens), tokens


def normalize_section_name(section: str) -> tuple[str, list[str]]:
    """Нормализация имени секции — аналогично title, но без удаления
    stopwords: в коротких именах секций они иногда несут смысл (напр. «по
    телефону»)."""
    folded = fold(section)
    raw_tokens = tokenize(folded)
    tokens = normalize_tokens(raw_tokens, keep_stopwords=True)
    return " ".join(tokens), tokens


# --------------------------------------------------------------------------- #
# Char n-grams (для доп. представления и тестов)
# --------------------------------------------------------------------------- #


def char_ngrams(text: str, n_min: int = 3, n_max: int = 5) -> list[str]:
    """Вернуть плоский список char-ngram от `n_min` до `n_max` включительно.

    Главным образом используется для тестов и подстраховки — в продакшн-
    пайплайне мы доверяем TfidfVectorizer с analyzer='char_wb'.
    """
    if not text:
        return []
    padded = f" {text} "
    result: list[str] = []
    for n in range(n_min, n_max + 1):
        if n <= 0 or n > len(padded):
            continue
        result.extend(padded[i : i + n] for i in range(len(padded) - n + 1))
    return result


__all__ = [
    "fold",
    "collapse_whitespace",
    "strip_punct",
    "tokenize",
    "light_stem_ru",
    "is_noise",
    "is_stopword",
    "normalize_tokens",
    "normalize_title",
    "normalize_section_name",
    "char_ngrams",
]
