"""Эвристики классификации осей секций.

Для каждой sibling-группы (parent-узел с ≥2 детьми) строим гипотезу
об оси:

- BUSINESS_VARIANT — дети различаются бизнес-вариантом (например: «по
  телефону», «по карте», «по реквизитам»). Формальные признаки: низкий
  overlap имён, высокий overlap title-шаблонов внутри каждого ребёнка,
  наличие variant-токенов.
- FEATURE_GROUP — дети описывают разные фичи в рамках большого раздела.
  Признак: низкий overlap имён, низкий overlap title-шаблонов (титулы
  у разных детей существенно различаются).
- TECH_GROUP — организационная секция: регресс/смоук/ручные/авто и т.п.
- UNKNOWN — недостаточно данных. Такие уходят в Qwen review pack.

Гипотеза возвращается как `SectionAxis` c пометками «confidence» и «reason»,
на основании которых Python-сайд решает, нужен ли Qwen-ревью.
"""

from __future__ import annotations

from collections.abc import Iterable

from .models import AxisType, SectionAxis, SectionValue
from .section_tree import SectionTree, SiblingGroupStats


# Порог уверенности ниже которого — отправляем в Qwen review pack.
CONFIDENCE_REVIEW_THRESHOLD: float = 0.55


def classify_axis(stats: SiblingGroupStats) -> SectionAxis:
    """Построить гипотезу по одной sibling-группе."""
    axis_type = AxisType.UNKNOWN
    confidence = 0.0
    reasons: list[str] = []

    # 1. TECH_GROUP по явным маркерам (высший приоритет — они бесспорны).
    if stats.child_count and stats.tech_token_hits / stats.child_count >= 0.5:
        axis_type = AxisType.TECH_GROUP
        confidence = 0.85
        reasons.append(
            f"у {stats.tech_token_hits} из {stats.child_count} секций в имени "
            f"встречается технический/организационный маркер"
        )

    # 2. BUSINESS_VARIANT — variant-hits или устойчивая комбинация признаков.
    elif stats.variant_token_hits >= 1 and stats.child_name_overlap <= 0.4:
        axis_type = AxisType.BUSINESS_VARIANT
        # больше совпадения шаблонов названий тестов -> больше уверенность
        confidence = min(0.95, 0.55 + 0.4 * stats.title_pattern_overlap + 0.05 * min(stats.variant_token_hits, 3))
        reasons.append(
            f"seed-variant совпадения: {stats.variant_token_hits}; "
            f"overlap имён детей: {stats.child_name_overlap:.2f}; "
            f"overlap title-шаблонов: {stats.title_pattern_overlap:.2f}"
        )

    # 3. Косвенный BUSINESS_VARIANT — нет seed, но characteristic сигнал.
    elif (
        stats.title_pattern_overlap >= 0.45
        and stats.child_name_overlap <= 0.25
        and stats.child_count <= 6
    ):
        axis_type = AxisType.BUSINESS_VARIANT
        confidence = 0.55
        reasons.append(
            "дети имеют различающиеся имена, но похожие наборы title-токенов — "
            "вероятно, это один и тот же базовый сценарий с разными вариантами"
        )

    # 4. FEATURE_GROUP — дети полностью разные по содержимому.
    elif stats.title_pattern_overlap <= 0.2 and stats.child_name_overlap <= 0.25:
        axis_type = AxisType.FEATURE_GROUP
        confidence = 0.7
        reasons.append(
            "низкий overlap имён и title-шаблонов между детьми — это разные фичи"
        )

    # 5. Всё остальное — UNKNOWN.
    else:
        axis_type = AxisType.UNKNOWN
        confidence = 0.35
        reasons.append(
            "эвристика не уверена: "
            f"overlap имён {stats.child_name_overlap:.2f}, "
            f"overlap title-шаблонов {stats.title_pattern_overlap:.2f}, "
            f"variant hits {stats.variant_token_hits}"
        )

    dimension_name = ""
    if axis_type is AxisType.BUSINESS_VARIANT:
        # Пытаемся собрать человеко-читаемое имя оси: самый частый distinctive-токен
        dimension_name = _guess_dimension_name(stats)

    section_values = [
        SectionValue(
            section_name=child_name,
            normalized_value=_pick_value(stats, child_key),
        )
        for child_name, child_key in zip(stats.child_names, stats.child_keys)
    ]

    return SectionAxis(
        parent_section=stats.parent_key or stats.parent_name,
        axis_type=axis_type,
        dimension_name=dimension_name,
        confidence=confidence,
        reason="; ".join(reasons),
        section_values=section_values,
        child_name_overlap=stats.child_name_overlap,
        title_pattern_overlap=stats.title_pattern_overlap,
        variant_token_hits=stats.variant_token_hits,
        tech_token_hits=stats.tech_token_hits,
        child_count=stats.child_count,
    )


def _guess_dimension_name(stats: SiblingGroupStats) -> str:
    # Берём токены из distinctive и возвращаем как имя размерности, если оно стабильное.
    # Не пытаемся быть семантически точными — это лишь подсказка для Qwen/пользователя.
    first_tokens: list[str] = []
    for child_key in stats.child_keys:
        toks = stats.distinctive_tokens.get(child_key, [])
        if toks:
            first_tokens.append(toks[0])
    if first_tokens:
        return f"variant_of({' | '.join(first_tokens)})"
    return ""


def _pick_value(stats: SiblingGroupStats, child_key: str) -> str:
    toks = stats.distinctive_tokens.get(child_key, [])
    return toks[0] if toks else ""


def infer_all(tree: SectionTree) -> list[SectionAxis]:
    """Пройти по всем sibling-группам и собрать гипотезы."""
    axes: list[SectionAxis] = []
    for parent in tree.iter_sibling_groups():
        stats = tree.compute_stats(parent)
        axes.append(classify_axis(stats))
    # Стабильная сортировка для детерминизма выхода.
    axes.sort(key=lambda a: a.parent_section)
    return axes


def needs_qwen_review(axis: SectionAxis) -> bool:
    """Нужно ли отправить ось в review pack для Qwen CLI."""
    if axis.axis_type is AxisType.UNKNOWN:
        return True
    return axis.confidence < CONFIDENCE_REVIEW_THRESHOLD


def filter_for_review(axes: Iterable[SectionAxis]) -> list[SectionAxis]:
    return [a for a in axes if needs_qwen_review(a)]


__all__ = [
    "classify_axis",
    "infer_all",
    "needs_qwen_review",
    "filter_for_review",
    "CONFIDENCE_REVIEW_THRESHOLD",
]
