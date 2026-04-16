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

from pathlib import Path

import typer
from rich.console import Console

from tools.test_duplicate_audit.config import QWEN_RESULTS_DIR
from tools.test_duplicate_audit.io_utils import iter_jsonl, write_jsonl
from tools.test_duplicate_audit.models import PairReview, SectionAxisReview

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
        for obj in iter_jsonl(pairs_in):
            try:
                valid_pairs.append(PairReview.model_validate(obj))
            except Exception as exc:  # noqa: BLE001
                broken_pairs += 1
                console.print(f"[yellow]Битый pair-ответ, пропускаю: {exc}[/]")
    else:
        console.print(f"[yellow]{pairs_in} отсутствует — пропускаю pairs[/]")

    valid_sections: list[SectionAxisReview] = []
    broken_sections = 0
    if sections_in.exists():
        for obj in iter_jsonl(sections_in):
            try:
                valid_sections.append(SectionAxisReview.model_validate(obj))
            except Exception as exc:  # noqa: BLE001
                broken_sections += 1
                console.print(f"[yellow]Битый section-ответ, пропускаю: {exc}[/]")
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
