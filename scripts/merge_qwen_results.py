"""scripts/merge_qwen_results.py — шаг 5 пайплайна.

Валидирует JSONL-ответы Qwen CLI (pairs.jsonl, sections.jsonl) и готовит
промежуточный merged-артефакт для build_final_reports.py. Qwen имеет
приоритет над авто-разметкой.

В этом шаге самостоятельного мерджа с кандидатами не происходит —
build_final_reports.py читает оба источника. Этот скрипт лишь:
- валидирует форматы,
- печатает диагностику (сколько ответов от Qwen, сколько битых),
- опционально копирует результаты в `data/qwen_results/normalized.jsonl`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypeVar

import typer
from pydantic import BaseModel
from rich.console import Console

from tools.test_duplicate_audit.config import QWEN_RESULTS_DIR
from tools.test_duplicate_audit.io_utils import write_jsonl
from tools.test_duplicate_audit.models import PairReview, SectionAxisReview

T = TypeVar("T", bound=BaseModel)


def _load_lenient(
    path: Path, model: type[T], label: str, console: Console
) -> tuple[list[T], int]:
    """Прочитать JSONL, валидируя каждую строку через pydantic-модель.

    Битые JSON-строки и ответы, не проходящие валидацию, пропускаются и
    засчитываются в `broken`. Используем raw-чтение, а не iter_jsonl, чтобы
    обе причины поломки (json.loads и model_validate) ловились одинаково —
    иначе ValueError из генератора iter_jsonl пробил бы try/except.
    """
    valid: list[T] = []
    broken = 0
    with path.open("r", encoding="utf-8") as fh:
        for line_num, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                valid.append(model.model_validate(obj))
            except Exception as exc:  # noqa: BLE001
                broken += 1
                console.print(
                    f"[yellow]Битый {label}-ответ в {path.name}:{line_num}, пропускаю: {exc}[/]"
                )
    return valid, broken

app = typer.Typer(add_completion=False, no_args_is_help=False, help=__doc__)
console = Console()


@app.command()
def main(
    results_dir: Path = typer.Option(QWEN_RESULTS_DIR, "--results-dir"),
) -> None:
    results_dir.mkdir(parents=True, exist_ok=True)

    pairs_in = results_dir / "pairs.jsonl"
    sections_in = results_dir / "sections.jsonl"

    valid_pairs: list[PairReview] = []
    broken_pairs = 0
    if pairs_in.exists():
        valid_pairs, broken_pairs = _load_lenient(pairs_in, PairReview, "pair", console)
    else:
        console.print(f"[yellow]{pairs_in} отсутствует — пропускаю pairs[/]")

    valid_sections: list[SectionAxisReview] = []
    broken_sections = 0
    if sections_in.exists():
        valid_sections, broken_sections = _load_lenient(
            sections_in, SectionAxisReview, "section", console
        )
    else:
        console.print(f"[yellow]{sections_in} отсутствует — пропускаю sections[/]")

    # Нормализованные выходы (тот же набор полей, но валидированный).
    write_jsonl(results_dir / "pairs.normalized.jsonl", valid_pairs)
    write_jsonl(results_dir / "sections.normalized.jsonl", valid_sections)

    console.print(
        f"[green]OK[/] pairs: {len(valid_pairs)} валидных "
        f"({broken_pairs} битых); sections: {len(valid_sections)} валидных "
        f"({broken_sections} битых)."
    )


if __name__ == "__main__":
    app()
