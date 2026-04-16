"""Поиск кандидатных пар без эмбеддингов API.

Пайплайн:
1. Для всех тестов строим два TF-IDF представления (char и word ngrams).
2. Через kNN на char-TF-IDF отбираем top-K ближайших соседей каждого теста.
3. Для каждой пары вычисляем итоговый similarity:
       similarity = 0.55 * cos_char + 0.25 * cos_word + 0.20 * rapidfuzz_ratio
   Это «сырая» лексическая похожесть без section-модификаторов.
4. В `_classify_pair` применяем section-aware правила к confidence (а не
   к similarity): bonus при same_section, penalty при cross_business_variant.
   Держим similarity «сырым», чтобы пороги классификатора срабатывали
   корректно и чтобы отчёты показывали настоящую текстовую близость
   без скрытых модификаций.
5. Определяем variant-конфликт по variant-токенам (seed + auto из секций).
6. Выставляем авто-вердикт:
       LIKELY_DUPLICATE | POSSIBLE_DUPLICATE | RELATED_NOT_DUPLICATE
   и помечаем пограничные как `needs_qwen_review=True`.

Результат — список CandidatePair.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import numpy as np
from rapidfuzz import fuzz
from scipy.sparse import csr_matrix
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.neighbors import NearestNeighbors

from .config import (
    TFIDF_CHAR_NGRAM_RANGE,
    TFIDF_MAX_FEATURES,
    TFIDF_MIN_DF,
    TFIDF_WORD_NGRAM_RANGE,
    ScoreWeights,
    Thresholds,
)
from .models import (
    CandidatePair,
    ScoreBreakdown,
    SectionAxis,
    SectionRelation,
    TestItem,
    Verdict,
)
from .section_tree import SectionTree


@dataclass
class _VectorizedCorpus:
    """Кешируем TF-IDF представления, чтобы переиспользовать их между шагами."""

    vec_char: TfidfVectorizer
    vec_word: TfidfVectorizer
    matrix_char: csr_matrix
    matrix_word: csr_matrix


def vectorize_titles(titles_norm: Sequence[str]) -> _VectorizedCorpus:
    """Построить TF-IDF матрицы на нормализованных заголовках.

    char_wb добавляет границы слов (« w »), что делает сопоставление более
    устойчивым к вариациям окончаний, которые не срезал стемминг.
    """
    # Хотя бы одно не пустое значение должно быть, иначе sklearn упадёт.
    safe_titles = [t if t.strip() else "_" for t in titles_norm]

    vec_char = TfidfVectorizer(
        analyzer="char_wb",
        ngram_range=TFIDF_CHAR_NGRAM_RANGE,
        min_df=TFIDF_MIN_DF,
        max_features=TFIDF_MAX_FEATURES,
        sublinear_tf=True,
    )
    vec_word = TfidfVectorizer(
        analyzer="word",
        ngram_range=TFIDF_WORD_NGRAM_RANGE,
        min_df=TFIDF_MIN_DF,
        max_features=TFIDF_MAX_FEATURES,
        sublinear_tf=True,
    )
    matrix_char = vec_char.fit_transform(safe_titles)
    matrix_word = vec_word.fit_transform(safe_titles)
    return _VectorizedCorpus(
        vec_char=vec_char,
        vec_word=vec_word,
        matrix_char=matrix_char,
        matrix_word=matrix_word,
    )


def _top_k_neighbors(matrix: csr_matrix, k: int) -> tuple[np.ndarray, np.ndarray]:
    """Вернёт (indices, similarities) для top-K соседей каждой строки.

    Индексы и близости включают саму строку (distance=0), её потом удаляем
    на уровне пар. Возвращаем similarities = 1 - distance.
    """
    n = matrix.shape[0]
    effective_k = min(k + 1, n)
    nn = NearestNeighbors(metric="cosine", algorithm="brute", n_neighbors=effective_k)
    nn.fit(matrix)
    distances, indices = nn.kneighbors(matrix, n_neighbors=effective_k, return_distance=True)
    sims = np.clip(1.0 - distances, 0.0, 1.0)
    return indices, sims


def _variant_tokens_in(tokens: Iterable[str], variants: set[str]) -> set[str]:
    return {t for t in tokens if t in variants}


def _pairwise_variant_conflict(
    a_tokens: list[str], b_tokens: list[str], variants: set[str]
) -> tuple[bool, list[str]]:
    """Найти variant-токены, которые есть у одного и НЕТ у другого.

    Конфликтом считаем не просто разные toketens, а именно противопоставление:
    одна сторона явно содержит variant-токен, другая не содержит ни его, ни
    эквивалентов (эквиваленты для простоты считаем всех variant-ами).
    """
    a_vars = _variant_tokens_in(a_tokens, variants)
    b_vars = _variant_tokens_in(b_tokens, variants)
    if not a_vars and not b_vars:
        return False, []
    only_a = a_vars - b_vars
    only_b = b_vars - a_vars
    if not only_a and not only_b:
        return False, sorted(a_vars)
    conflict_tokens = sorted(only_a | only_b)
    return True, conflict_tokens


def _section_relation(
    a: TestItem,
    b: TestItem,
    axes_by_parent: dict[str, SectionAxis],
    tree: SectionTree,
) -> tuple[SectionRelation, bool, bool]:
    """Определить, в каком родственном отношении секции двух тестов.

    Возвращает (relation, same_section, cross_business_variant).
    """
    path_a = a.section_path_parts
    path_b = b.section_path_parts

    if path_a == path_b and path_a:
        return "same_section", True, False

    parent_key, common_len = tree.find_common_parent(path_a, path_b)
    if common_len == 0:
        return "unknown", False, False

    # Смотрим ось на уровне «где начинается расхождение».
    # parent_key — общий префикс, под ним лежат два ветвления.
    axis = axes_by_parent.get(parent_key)
    if axis is None:
        # parent_key может быть пустым (разные корневые). Это практически cross-feature.
        return "cross_feature_group", False, False

    if axis.axis_type.value == "BUSINESS_VARIANT":
        return "cross_business_variant", False, True
    if axis.axis_type.value == "FEATURE_GROUP":
        return "cross_feature_group", False, False
    if axis.axis_type.value == "TECH_GROUP":
        return "same_feature_group", False, False
    return "unknown", False, False


def _classify_pair(
    score: ScoreBreakdown, thresholds: Thresholds
) -> tuple[Verdict, float, str, bool, str]:
    """Правила авто-классификации пары.

    Возвращает (verdict, confidence, explanation, needs_review, review_reason).
    """
    sim = score.similarity
    notes: list[str] = []

    # 1) Variant-конфликт — сильнейший сигнал «не дубль, но родственные».
    if score.variant_conflict:
        notes.append(
            "обнаружен variant-конфликт по токенам "
            f"{score.variant_conflict_tokens}"
        )
        if sim >= thresholds.likely_duplicate_min:
            return (
                Verdict.RELATED_NOT_DUPLICATE,
                min(0.9, sim),
                "; ".join(notes + ["очень похожие тексты, но бизнес-варианты различаются"]),
                True,
                "variant-конфликт при высоком similarity — Qwen должен уточнить",
            )
        if sim >= thresholds.possible_duplicate_min:
            return (
                Verdict.RELATED_NOT_DUPLICATE,
                sim,
                "; ".join(notes + ["разные бизнес-варианты"]),
                False,
                "",
            )
        # низкий — не кандидат, но если уже сюда попали — пометим related
        return (
            Verdict.RELATED_NOT_DUPLICATE,
            sim,
            "; ".join(notes),
            False,
            "",
        )

    # 2) Кросс business-variant секций без явного конфликта в title.
    if score.cross_business_variant:
        notes.append("тесты лежат в разных секциях одной business-variant оси")
        if sim >= thresholds.likely_duplicate_min:
            return (
                Verdict.RELATED_NOT_DUPLICATE,
                max(sim - thresholds.cross_business_variant_penalty, 0.5),
                "; ".join(notes + ["одинаковый базовый смысл — но организация указывает на разные варианты"]),
                True,
                "высокая похожесть через business-variant границу",
            )
        return (
            Verdict.RELATED_NOT_DUPLICATE,
            max(sim - thresholds.cross_business_variant_penalty, 0.3),
            "; ".join(notes),
            False,
            "",
        )

    # 3) Обычное similarity-дерево.
    if sim >= thresholds.likely_duplicate_min:
        return (
            Verdict.LIKELY_DUPLICATE,
            min(0.97, sim + (thresholds.same_section_bonus if score.same_section else 0.0)),
            f"высокая лексическая похожесть {sim:.2f}"
            + (" при одной секции" if score.same_section else ""),
            False,
            "",
        )
    if sim >= thresholds.possible_duplicate_min:
        return (
            Verdict.POSSIBLE_DUPLICATE,
            sim,
            f"умеренно высокая похожесть {sim:.2f} — без steps/expected уверенно сказать нельзя",
            True,
            "пограничная похожесть — нужен смысловой разбор Qwen",
        )
    if sim >= thresholds.related_min:
        return (
            Verdict.RELATED_NOT_DUPLICATE,
            sim,
            f"похожесть {sim:.2f} — скорее родственные, чем дубли",
            True,
            "низкая похожесть — Qwen должен подтвердить, что это не вариант одного теста",
        )
    # совсем мало — не кандидат
    return (
        Verdict.NOT_DUPLICATE,
        sim,
        f"похожесть {sim:.2f} ниже порога кандидатов",
        False,
        "",
    )


def _combined_similarity(
    cos_char: float,
    cos_word: float,
    token_set_ratio_01: float,
    weights: ScoreWeights,
) -> float:
    total_w = weights.tfidf_char + weights.tfidf_word + weights.token_set_ratio
    if total_w <= 0:
        return 0.0
    return (
        weights.tfidf_char * cos_char
        + weights.tfidf_word * cos_word
        + weights.token_set_ratio * token_set_ratio_01
    ) / total_w


def generate_candidate_pairs(
    items: list[TestItem],
    *,
    tree: SectionTree,
    axes: list[SectionAxis],
    thresholds: Thresholds,
    weights: ScoreWeights,
    variant_tokens: set[str],
) -> list[CandidatePair]:
    """Главный entry-point генерации кандидатных пар.

    Источники кандидатов:
    - kNN top-K на char-TF-IDF (основной блокирующий фильтр);
    - все пары внутри одной leaf-секции (same-section fallback). Он
      ловит семантические перефразы в одной секции, которые лексически
      далеки друг от друга (напр. «Создание вклада» vs «Открытие нового
      вклада»). Для small-leaf секций это дёшево.
    """
    if len(items) < 2:
        return []

    titles_norm = [it.title_norm or "_" for it in items]
    corpus = vectorize_titles(titles_norm)

    # kNN-блокирование на char-матрице (она чувствительнее к мелким отличиям).
    indices, sims_char = _top_k_neighbors(corpus.matrix_char, k=thresholds.top_k_neighbors)

    axes_by_parent = {a.parent_section: a for a in axes}

    # Сбор кандидатных индексов из двух источников.
    candidate_pairs_idx: set[tuple[int, int]] = set()
    for i, neighbors in enumerate(indices):
        for pos, j in enumerate(neighbors):
            if int(j) == i:
                continue
            candidate_pairs_idx.add((min(i, int(j)), max(i, int(j))))

    # Same-section fallback: все пары в одной leaf-секции.
    by_leaf_section: dict[str, list[int]] = {}
    for i, it in enumerate(items):
        by_leaf_section.setdefault(it.full_section_path, []).append(i)
    for _, idxs in by_leaf_section.items():
        if len(idxs) < 2:
            continue
        for a_idx in range(len(idxs)):
            for b_idx in range(a_idx + 1, len(idxs)):
                candidate_pairs_idx.add((idxs[a_idx], idxs[b_idx]))

    results: list[CandidatePair] = []

    for i, j in candidate_pairs_idx:
        a = items[i]
        b = items[j]
        same_leaf = a.full_section_path == b.full_section_path and a.full_section_path

        cos_char = _cosine_pair(corpus.matrix_char, i, j)
        # kNN уже проверил порог, но same-section пары могли зайти в обход.
        # Для same-section относимся мягче: порог 0.25, иначе 0.45.
        min_char = 0.25 if same_leaf else thresholds.min_tfidf_char_cosine
        if cos_char < min_char:
            continue

        cos_word = _cosine_pair(corpus.matrix_word, i, j)
        token_set = fuzz.token_set_ratio(a.title_norm, b.title_norm)
        partial = fuzz.partial_ratio(a.title_norm, b.title_norm)
        token_set_01 = token_set / 100.0

        # Верификация: для не-same-section пар требуем хотя бы один сильный сигнал.
        if not same_leaf:
            if (
                token_set < thresholds.min_token_set_ratio
                and cos_word < thresholds.min_tfidf_word_cosine
            ):
                continue

        variant_conflict, variant_tokens_hit = _pairwise_variant_conflict(
            a.title_tokens + a.section_tokens,
            b.title_tokens + b.section_tokens,
            variant_tokens,
        )

        relation, same_section, cross_biz = _section_relation(a, b, axes_by_parent, tree)

        # similarity — чисто текстовая мера (TF-IDF + rapidfuzz). Штраф за
        # cross_business_variant здесь НЕ применяем: иначе он бы учитывался
        # дважды (ещё раз внутри `_classify_pair`), а порог 0.88 в ветке
        # cross_biz становился бы недостижим (sim ≤ 1 - 0.25 = 0.75). Все
        # section-aware модификаторы применяются только к confidence в
        # `_classify_pair`, симметрично с same_section_bonus.
        similarity = _combined_similarity(cos_char, cos_word, token_set_01, weights)

        score = ScoreBreakdown(
            tfidf_char=round(cos_char, 4),
            tfidf_word=round(cos_word, 4),
            token_set_ratio=round(token_set_01, 4),
            partial_ratio=round(partial / 100.0, 4),
            similarity=round(similarity, 4),
            variant_conflict=variant_conflict,
            variant_conflict_tokens=variant_tokens_hit,
            same_section=same_section,
            same_parent_section=_same_parent(a, b),
            cross_business_variant=cross_biz,
            section_relation=relation,
        )

        verdict, confidence, explanation, needs_review, review_reason = _classify_pair(
            score, thresholds
        )

        # Same-section пары с низкой уверенностью всё равно эмитим как
        # POSSIBLE_DUPLICATE на ревью Qwen — лексической похожести может быть
        # недостаточно, но секция даёт сильный prior.
        if verdict is Verdict.NOT_DUPLICATE:
            # Same-leaf пары всегда эмитим: их базовый prior на дубль высок,
            # а без Qwen мы ничего не можем с ними решить. Классификация
            # идёт через POSSIBLE_DUPLICATE → уходит в review pack.
            if same_leaf and similarity >= 0.28:
                verdict = Verdict.POSSIBLE_DUPLICATE
                confidence = max(0.5, similarity)
                explanation = (
                    f"похожесть {similarity:.2f} низкая, но тесты в одной секции "
                    f"«{a.full_section_path}» — может быть семантический перефраз"
                )
                needs_review = True
                review_reason = "same-section pair с низкой лексической похожестью"
            else:
                continue

        results.append(
            CandidatePair(
                test_a_id=a.test_id,
                test_b_id=b.test_id,
                test_a_title=a.title,
                test_b_title=b.title,
                test_a_section=a.full_section_path,
                test_b_section=b.full_section_path,
                score=score,
                auto_verdict=verdict,
                auto_confidence=round(confidence, 4),
                explanation=explanation,
                needs_qwen_review=needs_review,
                review_reason=review_reason,
            )
        )

    # Сортировка: сначала LIKELY, потом POSSIBLE, затем RELATED; внутри — по similarity убыв.
    verdict_order = {
        Verdict.LIKELY_DUPLICATE: 0,
        Verdict.POSSIBLE_DUPLICATE: 1,
        Verdict.RELATED_NOT_DUPLICATE: 2,
        Verdict.NOT_DUPLICATE: 3,
    }
    results.sort(
        key=lambda p: (
            verdict_order[p.auto_verdict],
            -p.score.similarity,
            p.test_a_id,
            p.test_b_id,
        )
    )
    return results


def _cosine_pair(matrix: csr_matrix, i: int, j: int) -> float:
    """Вычислить cosine-similarity между двумя строками разреженной матрицы."""
    row_i = matrix[i]
    row_j = matrix[j]
    # cosine_similarity возвращает matrix 1x1
    val = cosine_similarity(row_i, row_j)[0, 0]
    if math.isnan(val):
        return 0.0
    return float(np.clip(val, 0.0, 1.0))


def _same_parent(a: TestItem, b: TestItem) -> bool:
    if not a.section_path_parts or not b.section_path_parts:
        return False
    return a.section_path_parts[:-1] == b.section_path_parts[:-1]


__all__ = [
    "vectorize_titles",
    "generate_candidate_pairs",
]
