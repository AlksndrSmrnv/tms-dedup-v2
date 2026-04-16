"""Константы и дефолтные пути пайплайна.

Все пути можно переопределить CLI-флагами. Значения здесь подобраны
под небольшую модель ~2500 тестов. Основной принцип: явное лучше неявного,
поэтому все пороги собраны в одном месте и документированы.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------- #
# Пути по умолчанию
# --------------------------------------------------------------------------- #

PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
DATA_DIR: Path = PROJECT_ROOT / "data"
SAMPLES_DIR: Path = PROJECT_ROOT / "data_samples"

DATASET_PATH: Path = DATA_DIR / "dataset.jsonl"
SECTION_AXES_AUTO_PATH: Path = DATA_DIR / "section_axes.auto.jsonl"
CANDIDATE_PAIRS_PATH: Path = DATA_DIR / "candidate_pairs.jsonl"

QWEN_PACKS_DIR: Path = DATA_DIR / "qwen_packs"
QWEN_RESULTS_DIR: Path = DATA_DIR / "qwen_results"
REPORTS_DIR: Path = DATA_DIR / "reports"

DEFAULT_SECTION_SEP: str = "/"

# --------------------------------------------------------------------------- #
# Пороги кандидатной генерации и классификации
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Thresholds:
    """Набор порогов, используемых в pipeline.

    similarity = 0.55 * tfidf_char + 0.25 * tfidf_word + 0.20 * rapidfuzz_token_set
    """

    # top-K ближайших соседей на каждый тест (блокирование O(N^2))
    top_k_neighbors: int = 25

    # минимальные TF-IDF cos similarities для попадания в короткий список
    min_tfidf_char_cosine: float = 0.45
    min_tfidf_word_cosine: float = 0.30

    # минимальный rapidfuzz token_set_ratio (0-100) для попадания в кандидаты
    min_token_set_ratio: int = 70

    # границы итоговой уверенности (0..1) для вердиктов
    likely_duplicate_min: float = 0.88
    possible_duplicate_min: float = 0.75
    related_min: float = 0.60

    # штраф при кросс-business-variant секциях
    cross_business_variant_penalty: float = 0.25

    # бонус при совпадении секции
    same_section_bonus: float = 0.05


@dataclass(frozen=True)
class ScoreWeights:
    """Веса итогового similarity score.

    Сумма не обязана быть ровно 1.0 — на выходе нормализуем.
    """

    tfidf_char: float = 0.55
    tfidf_word: float = 0.25
    token_set_ratio: float = 0.20


THRESHOLDS = Thresholds()
WEIGHTS = ScoreWeights()

# --------------------------------------------------------------------------- #
# TF-IDF параметры
# --------------------------------------------------------------------------- #

TFIDF_CHAR_NGRAM_RANGE: tuple[int, int] = (3, 5)
TFIDF_WORD_NGRAM_RANGE: tuple[int, int] = (1, 2)
TFIDF_MIN_DF: int = 1
TFIDF_MAX_FEATURES: int = 50000

# --------------------------------------------------------------------------- #
# Seed-словари (намеренно короткие; остальные variant-токены ищутся
# статистически на основе sibling-секций).
# --------------------------------------------------------------------------- #

SEED_VARIANT_TOKENS: frozenset[str] = frozenset(
    {
        # способы перевода / каналы
        # NB: токены хранятся в форме, совпадающей с выходом light_stem_ru,
        # т.к. сравнение всегда идёт против уже стеммированных токенов.
        "телефон",
        "номер",
        "карт",
        "реквизит",
        "сбп",
        "qr",
        "кошелек",
        "кошелёк",
        "счет",
        "счёт",
        # платформы
        "web",
        "веб",
        "mobile",
        "мобильн",
        "android",
        "ios",
        "desktop",
        "браузер",
        # роли / контексты
        "клиент",
        "оператор",
        "админ",
        "юл",
        "фл",
    }
)

SEED_TECH_SECTION_TOKENS: frozenset[str] = frozenset(
    {
        # NB: как и в SEED_VARIANT_TOKENS, токены хранятся в форме, совпадающей
        # с выходом light_stem_ru (сравнение идёт против стеммированных токенов).
        "регресс",
        "регресси",
        "регрессионн",
        "smoke",
        "смоук",
        "санит",
        "sanity",
        "ручн",
        "manual",
        "авт",
        "auto",
        "automation",
        "e2e",
        "интеграционн",
        "integration",
        "unit",
        "api",
        "ui",
    }
)

# --------------------------------------------------------------------------- #
# Русские стоп-слова / шумовые
# --------------------------------------------------------------------------- #

NOISE_WORDS: frozenset[str] = frozenset(
    {
        "тест",
        "тесты",
        "тестирование",
        "проверка",
        "проверить",
        "проверяем",
        "кейс",
        "testcase",
        "case",
        "check",
    }
)

STOPWORDS: frozenset[str] = frozenset(
    {
        "и",
        "в",
        "на",
        "по",
        "с",
        "со",
        "из",
        "за",
        "у",
        "о",
        "об",
        "для",
        "от",
        "до",
        "при",
        "как",
        "что",
        "это",
        "а",
        "но",
        "или",
        "же",
        "ли",
        "бы",
        "не",
        "то",
        "же",
        "the",
        "a",
        "an",
        "of",
        "to",
        "in",
        "for",
        "on",
        "with",
        "by",
        "is",
        "are",
    }
)


@dataclass
class PipelineConfig:
    """Динамическая конфигурация, переопределяемая CLI."""

    input_path: Path | None = None
    section_sep: str = DEFAULT_SECTION_SEP
    data_dir: Path = DATA_DIR
    thresholds: Thresholds = field(default_factory=lambda: THRESHOLDS)
    weights: ScoreWeights = field(default_factory=lambda: WEIGHTS)


__all__ = [
    "PROJECT_ROOT",
    "DATA_DIR",
    "SAMPLES_DIR",
    "DATASET_PATH",
    "SECTION_AXES_AUTO_PATH",
    "CANDIDATE_PAIRS_PATH",
    "QWEN_PACKS_DIR",
    "QWEN_RESULTS_DIR",
    "REPORTS_DIR",
    "DEFAULT_SECTION_SEP",
    "Thresholds",
    "ScoreWeights",
    "THRESHOLDS",
    "WEIGHTS",
    "TFIDF_CHAR_NGRAM_RANGE",
    "TFIDF_WORD_NGRAM_RANGE",
    "TFIDF_MIN_DF",
    "TFIDF_MAX_FEATURES",
    "SEED_VARIANT_TOKENS",
    "SEED_TECH_SECTION_TOKENS",
    "NOISE_WORDS",
    "STOPWORDS",
    "PipelineConfig",
]
