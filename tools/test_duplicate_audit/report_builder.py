"""Сборка финальных отчётов.

На вход — список кандидатных пар (с авто-вердиктами) и JSONL результатов
Qwen CLI ревью. На выход — 4 CSV + человеко-читаемый summary.md.

Qwen имеет приоритет над авто-разметкой, если его ответ валиден.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from pathlib import Path

from .io_utils import iter_jsonl, write_csv
from .models import (
    AxisType,
    CandidatePair,
    FinalPairRecord,
    PairReview,
    SectionAxis,
    SectionAxisReview,
    Verdict,
)


# --------------------------------------------------------------------------- #
# Merge Qwen → CandidatePair → FinalPairRecord
# --------------------------------------------------------------------------- #


def load_pair_reviews(path: Path) -> dict[tuple[str, str], PairReview]:
    """Загрузить Qwen-ответы по парам. Пропускаем битые записи с логом."""
    if not path.exists():
        return {}
    index: dict[tuple[str, str], PairReview] = {}
    for obj in iter_jsonl(path):
        try:
            review = PairReview.model_validate(obj)
        except Exception:
            # Битый ответ — пропускаем, не валим пайплайн.
            continue
        key = _norm_pair_key(review.test_a_id, review.test_b_id)
        index[key] = review
    return index


def load_axis_reviews(path: Path) -> dict[str, SectionAxisReview]:
    if not path.exists():
        return {}
    index: dict[str, SectionAxisReview] = {}
    for obj in iter_jsonl(path):
        try:
            review = SectionAxisReview.model_validate(obj)
        except Exception:
            continue
        index[review.parent_section] = review
    return index


def _norm_pair_key(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


def merge_pairs(
    candidates: Iterable[CandidatePair],
    qwen_reviews: dict[tuple[str, str], PairReview],
) -> list[FinalPairRecord]:
    final: list[FinalPairRecord] = []
    for p in candidates:
        key = _norm_pair_key(p.test_a_id, p.test_b_id)
        review = qwen_reviews.get(key)
        if review is not None:
            final.append(
                FinalPairRecord(
                    test_a_id=p.test_a_id,
                    test_b_id=p.test_b_id,
                    test_a_title=p.test_a_title,
                    test_b_title=p.test_b_title,
                    test_a_section=p.test_a_section,
                    test_b_section=p.test_b_section,
                    verdict=review.verdict,
                    confidence=review.confidence,
                    source="qwen",
                    section_relation=review.section_relation,
                    different_dimensions=review.different_dimensions,
                    explanation=review.explanation or p.explanation,
                    similarity=p.score.similarity,
                )
            )
        else:
            final.append(
                FinalPairRecord(
                    test_a_id=p.test_a_id,
                    test_b_id=p.test_b_id,
                    test_a_title=p.test_a_title,
                    test_b_title=p.test_b_title,
                    test_a_section=p.test_a_section,
                    test_b_section=p.test_b_section,
                    verdict=p.auto_verdict,
                    confidence=p.auto_confidence,
                    source="auto",
                    section_relation=p.score.section_relation,
                    different_dimensions=[],
                    explanation=p.explanation,
                    similarity=p.score.similarity,
                )
            )
    return final


def merge_axes(
    auto: Iterable[SectionAxis],
    qwen: dict[str, SectionAxisReview],
) -> list[tuple[SectionAxis, SectionAxisReview | None]]:
    result: list[tuple[SectionAxis, SectionAxisReview | None]] = []
    for axis in auto:
        result.append((axis, qwen.get(axis.parent_section)))
    return result


# --------------------------------------------------------------------------- #
# CSV-отчёты
# --------------------------------------------------------------------------- #


PAIR_CSV_FIELDS = [
    "test_a_id",
    "test_b_id",
    "verdict",
    "confidence",
    "similarity",
    "source",
    "section_relation",
    "different_dimensions",
    "test_a_title",
    "test_b_title",
    "test_a_section",
    "test_b_section",
    "explanation",
]


def write_pair_reports(records: list[FinalPairRecord], out_dir: Path) -> dict[str, int]:
    """Разложить записи по CSV-файлам в соответствии с вердиктом."""
    groups: dict[Verdict, list[FinalPairRecord]] = {v: [] for v in Verdict}
    for r in records:
        groups[r.verdict].append(r)

    file_map = {
        Verdict.LIKELY_DUPLICATE: "likely_duplicates.csv",
        Verdict.POSSIBLE_DUPLICATE: "possible_duplicates.csv",
        Verdict.RELATED_NOT_DUPLICATE: "related_not_duplicates.csv",
        Verdict.NOT_DUPLICATE: "not_duplicates.csv",
    }

    counts: dict[str, int] = {}
    for verdict, fname in file_map.items():
        path = out_dir / fname
        rows = [_pair_to_row(r) for r in groups[verdict]]
        write_csv(path, rows, PAIR_CSV_FIELDS)
        counts[fname] = len(rows)
    return counts


def _pair_to_row(r: FinalPairRecord) -> dict[str, str]:
    return {
        "test_a_id": r.test_a_id,
        "test_b_id": r.test_b_id,
        "verdict": r.verdict.value,
        "confidence": f"{r.confidence:.3f}",
        "similarity": f"{r.similarity:.3f}",
        "source": r.source,
        "section_relation": r.section_relation,
        "different_dimensions": "; ".join(r.different_dimensions),
        "test_a_title": r.test_a_title,
        "test_b_title": r.test_b_title,
        "test_a_section": r.test_a_section,
        "test_b_section": r.test_b_section,
        "explanation": r.explanation,
    }


AXIS_CSV_FIELDS = [
    "parent_section",
    "axis_type",
    "dimension_name",
    "confidence",
    "source",
    "child_count",
    "child_name_overlap",
    "title_pattern_overlap",
    "variant_token_hits",
    "tech_token_hits",
    "reason",
    "section_values",
]


def write_axes_report(
    merged: list[tuple[SectionAxis, SectionAxisReview | None]],
    out_dir: Path,
) -> int:
    rows: list[dict[str, str]] = []
    for auto, qwen in merged:
        axis_type = qwen.axis_type if qwen else auto.axis_type
        dimension = qwen.dimension_name if qwen else auto.dimension_name
        confidence = qwen.confidence if qwen else auto.confidence
        reason = qwen.reason if qwen else auto.reason
        section_values = qwen.section_values if qwen else auto.section_values
        source = "qwen" if qwen else "auto"

        rows.append(
            {
                "parent_section": auto.parent_section,
                "axis_type": axis_type.value if isinstance(axis_type, AxisType) else str(axis_type),
                "dimension_name": dimension,
                "confidence": f"{confidence:.3f}",
                "source": source,
                "child_count": str(auto.child_count),
                "child_name_overlap": f"{auto.child_name_overlap:.3f}",
                "title_pattern_overlap": f"{auto.title_pattern_overlap:.3f}",
                "variant_token_hits": str(auto.variant_token_hits),
                "tech_token_hits": str(auto.tech_token_hits),
                "reason": reason,
                "section_values": "; ".join(
                    f"{sv.section_name}={sv.normalized_value}" if sv.normalized_value else sv.section_name
                    for sv in section_values
                ),
            }
        )
    write_csv(out_dir / "section_axis_hypotheses.csv", rows, AXIS_CSV_FIELDS)
    return len(rows)


# --------------------------------------------------------------------------- #
# Human-readable summary
# --------------------------------------------------------------------------- #


def write_summary_md(
    pair_records: list[FinalPairRecord],
    merged_axes: list[tuple[SectionAxis, SectionAxisReview | None]],
    out_dir: Path,
    total_tests: int,
) -> None:
    verdict_counts = Counter(r.verdict.value for r in pair_records)
    source_counts = Counter(r.source for r in pair_records)
    axis_counts: Counter[str] = Counter()
    for auto, qwen in merged_axes:
        axis_type = qwen.axis_type if qwen else auto.axis_type
        axis_counts[axis_type.value if isinstance(axis_type, AxisType) else str(axis_type)] += 1

    lines: list[str] = []
    lines.append("# TMS Duplicate Audit — итоговый отчёт")
    lines.append("")
    lines.append(f"Всего тестов: **{total_tests}**")
    lines.append(f"Всего кандидатных пар: **{len(pair_records)}**")
    lines.append("")
    lines.append("## Распределение по вердиктам")
    for verdict in [
        Verdict.LIKELY_DUPLICATE,
        Verdict.POSSIBLE_DUPLICATE,
        Verdict.RELATED_NOT_DUPLICATE,
        Verdict.NOT_DUPLICATE,
    ]:
        lines.append(f"- **{verdict.value}**: {verdict_counts.get(verdict.value, 0)}")
    lines.append("")
    lines.append("## Источник вердикта")
    lines.append(f"- auto (Python heuristics): {source_counts.get('auto', 0)}")
    lines.append(f"- qwen (LLM review): {source_counts.get('qwen', 0)}")
    lines.append("")
    lines.append("## Распределение осей секций")
    for k, v in axis_counts.most_common():
        lines.append(f"- **{k}**: {v}")
    lines.append("")
    lines.append("## Важные ограничения метода")
    lines.append(
        "- Используются только `title` и `full_section_path`. Шаги, "
        "expected, предусловия и параметры недоступны — все вердикты "
        "вероятностные."
    )
    lines.append(
        "- `LIKELY_DUPLICATE` не означает 100% дубль. Это сильная "
        "гипотеза; финальное решение принимает человек."
    )
    lines.append(
        "- Тесты, различающиеся бизнес-вариантом (телефон vs карта), "
        "классифицируются как `RELATED_NOT_DUPLICATE` — это намеренно."
    )
    lines.append("")
    lines.append("## Файлы")
    lines.append("- `likely_duplicates.csv`")
    lines.append("- `possible_duplicates.csv`")
    lines.append("- `related_not_duplicates.csv`")
    lines.append("- `not_duplicates.csv` (обычно пустой — кандидаты ниже порога не эмитятся)")
    lines.append("- `section_axis_hypotheses.csv`")
    lines.append("")

    (out_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")


__all__ = [
    "load_pair_reviews",
    "load_axis_reviews",
    "merge_pairs",
    "merge_axes",
    "write_pair_reports",
    "write_axes_report",
    "write_summary_md",
]
