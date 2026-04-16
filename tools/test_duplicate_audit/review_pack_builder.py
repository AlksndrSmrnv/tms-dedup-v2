"""Сборка review-packs для интерактивной работы с Qwen CLI.

Python не вызывает Qwen (он не headless). Вместо этого мы кладём в
`data/qwen_packs/` два типа пачек:

1. `section_axes_review.jsonl` + `.md` — sibling-группы с UNKNOWN/слабой
   гипотезой. Пользователь в интерактивной сессии говорит:
       "Примени skill test-duplicate-audit к data/qwen_packs/section_axes_review.md"
   и сохраняет ответы в `data/qwen_results/sections.jsonl`.

2. `pairs_to_review.jsonl` + `.md` — пограничные пары. Аналогично,
   результаты → `data/qwen_results/pairs.jsonl`.

Markdown пишем человеко-читаемо, JSONL — машинно для merge-скрипта. Оба
файла содержат заголовок с чёткой инструкцией куда сохранять ответы.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .io_utils import ensure_dir, write_jsonl
from .models import CandidatePair, SectionAxis


# --------------------------------------------------------------------------- #
# Section axes pack
# --------------------------------------------------------------------------- #


def build_section_axes_pack(
    axes: Iterable[SectionAxis],
    out_jsonl: Path,
    out_md: Path,
) -> tuple[int, int]:
    """Записать JSONL+MD пак для sibling-групп. Вернуть (count_jsonl, count_md_blocks)."""
    items = list(axes)
    write_jsonl(out_jsonl, items)

    md_lines: list[str] = []
    md_lines.append("# Qwen review pack — sibling sections")
    md_lines.append("")
    md_lines.append(
        "Примени skill `test-duplicate-audit` (prompt `infer_section_axes.md`). "
        "Для каждого блока верни один JSON-объект, совпадающий по схеме со "
        "`schemas/section_axis.schema.json`. Итог сохрани в "
        "`data/qwen_results/sections.jsonl` — по одному объекту в строку."
    )
    md_lines.append("")
    md_lines.append(
        "Правила интерпретации: см. SKILL.md. Коротко: BUSINESS_VARIANT — "
        "дети различаются бизнес-вариантом; FEATURE_GROUP — разные фичи; "
        "TECH_GROUP — организационные секции (регресс/смоук/…); UNKNOWN — "
        "когда нельзя уверенно отнести."
    )
    md_lines.append("")
    md_lines.append(f"Всего блоков: **{len(items)}**.")
    md_lines.append("")

    for idx, axis in enumerate(items, start=1):
        md_lines.append(f"## {idx}. parent_section: `{axis.parent_section or '<root>'}`")
        md_lines.append("")
        md_lines.append(
            f"- **Авто-гипотеза:** {axis.axis_type.value} "
            f"(confidence={axis.confidence:.2f})"
        )
        md_lines.append(f"- **Обоснование:** {axis.reason}")
        md_lines.append(
            f"- **Статистика:** child_count={axis.child_count}, "
            f"overlap имён={axis.child_name_overlap:.2f}, "
            f"overlap title-шаблонов={axis.title_pattern_overlap:.2f}, "
            f"variant hits={axis.variant_token_hits}, "
            f"tech hits={axis.tech_token_hits}"
        )
        md_lines.append("- **Дети:**")
        for sv in axis.section_values:
            md_lines.append(
                f"  - `{sv.section_name}`"
                + (f" → distinctive: `{sv.normalized_value}`" if sv.normalized_value else "")
            )
        md_lines.append("")
        md_lines.append("**Ожидаемый JSON-ответ Qwen:**")
        md_lines.append("")
        md_lines.append("```json")
        md_lines.append(
            "{\n"
            f"  \"parent_section\": \"{axis.parent_section}\",\n"
            "  \"axis_type\": \"BUSINESS_VARIANT | FEATURE_GROUP | TECH_GROUP | UNKNOWN\",\n"
            "  \"dimension_name\": \"\",\n"
            "  \"confidence\": 0.0,\n"
            "  \"reason\": \"\",\n"
            "  \"section_values\": [ { \"section_name\": \"\", \"normalized_value\": \"\" } ]\n"
            "}"
        )
        md_lines.append("```")
        md_lines.append("")
        md_lines.append("---")
        md_lines.append("")

    _write_text(out_md, "\n".join(md_lines))
    return len(items), len(items)


# --------------------------------------------------------------------------- #
# Candidate pairs pack
# --------------------------------------------------------------------------- #


def build_pairs_pack(
    pairs: Iterable[CandidatePair],
    out_jsonl: Path,
    out_md: Path,
) -> tuple[int, int]:
    """Записать JSONL+MD пак для пар, которым нужен ручной smart-ревью."""
    to_review = [p for p in pairs if p.needs_qwen_review]
    write_jsonl(out_jsonl, to_review)

    md_lines: list[str] = []
    md_lines.append("# Qwen review pack — candidate pairs")
    md_lines.append("")
    md_lines.append(
        "Примени skill `test-duplicate-audit` (prompt `review_candidate_pairs.md`). "
        "Для каждой пары верни один JSON-объект согласно "
        "`schemas/pair_review.schema.json`. Итог сохрани в "
        "`data/qwen_results/pairs.jsonl` — по одному объекту в строку."
    )
    md_lines.append("")
    md_lines.append(
        "**Ключевое правило:** если различие между тестами задаётся бизнес-вариантом "
        "(например, перевод по номеру телефона vs перевод по карте) — это "
        "НЕ дубль, а `RELATED_NOT_DUPLICATE`. Одинаковое название ≠ дубль, "
        "разные названия ≠ не-дубль. В сомнении — `POSSIBLE_DUPLICATE` или "
        "`RELATED_NOT_DUPLICATE`."
    )
    md_lines.append("")
    md_lines.append(f"Всего пар для ревью: **{len(to_review)}**.")
    md_lines.append("")

    for idx, pair in enumerate(to_review, start=1):
        md_lines.append(f"## {idx}. {pair.test_a_id}  ⇄  {pair.test_b_id}")
        md_lines.append("")
        md_lines.append(f"- **Test A:** `{pair.test_a_id}` — {pair.test_a_title}")
        md_lines.append(f"  - секция: `{pair.test_a_section}`")
        md_lines.append(f"- **Test B:** `{pair.test_b_id}` — {pair.test_b_title}")
        md_lines.append(f"  - секция: `{pair.test_b_section}`")
        md_lines.append("")
        md_lines.append(
            f"- **Авто-вердикт:** {pair.auto_verdict.value} "
            f"(similarity={pair.score.similarity:.2f}, confidence={pair.auto_confidence:.2f})"
        )
        md_lines.append(
            f"- **Score breakdown:** char={pair.score.tfidf_char:.2f}, "
            f"word={pair.score.tfidf_word:.2f}, "
            f"token_set={pair.score.token_set_ratio:.2f}, "
            f"partial={pair.score.partial_ratio:.2f}"
        )
        md_lines.append(f"- **Section relation:** `{pair.score.section_relation}`")
        if pair.score.variant_conflict:
            md_lines.append(
                f"- **Variant-конфликт:** `{', '.join(pair.score.variant_conflict_tokens)}`"
            )
        if pair.review_reason:
            md_lines.append(f"- **Почему на ревью:** {pair.review_reason}")
        md_lines.append(f"- **Объяснение:** {pair.explanation}")
        md_lines.append("")
        md_lines.append("**Ожидаемый JSON-ответ Qwen:**")
        md_lines.append("")
        md_lines.append("```json")
        md_lines.append(
            "{\n"
            f"  \"test_a_id\": \"{pair.test_a_id}\",\n"
            f"  \"test_b_id\": \"{pair.test_b_id}\",\n"
            "  \"verdict\": \"LIKELY_DUPLICATE | POSSIBLE_DUPLICATE | "
            "RELATED_NOT_DUPLICATE | NOT_DUPLICATE\",\n"
            "  \"confidence\": 0.0,\n"
            "  \"same_base_intent\": false,\n"
            "  \"different_dimensions\": [],\n"
            "  \"section_relation\": \"same_section | same_feature_group | "
            "cross_feature_group | cross_business_variant | unknown\",\n"
            "  \"explanation\": \"\"\n"
            "}"
        )
        md_lines.append("```")
        md_lines.append("")
        md_lines.append("---")
        md_lines.append("")

    _write_text(out_md, "\n".join(md_lines))
    return len(to_review), len(to_review)


def _write_text(path: Path, text: str) -> None:
    ensure_dir(path.parent)
    path.write_text(text, encoding="utf-8")


__all__ = [
    "build_section_axes_pack",
    "build_pairs_pack",
]
