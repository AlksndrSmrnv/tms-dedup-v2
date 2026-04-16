"""scripts/build_final_reports.py — шаг 6 пайплайна.

Собирает финальные CSV + summary.md в `data/reports/`. Qwen-ответы из
`data/qwen_results/` имеют приоритет над авто-разметкой.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from tools.test_duplicate_audit.config import (
    CANDIDATE_PAIRS_PATH,
    DATASET_PATH,
    QWEN_RESULTS_DIR,
    REPORTS_DIR,
    SECTION_AXES_AUTO_PATH,
)
from tools.test_duplicate_audit.io_utils import iter_jsonl
from tools.test_duplicate_audit.models import CandidatePair, SectionAxis
from tools.test_duplicate_audit.report_builder import (
    load_axis_reviews,
    load_pair_reviews,
    merge_axes,
    merge_pairs,
    write_axes_report,
    write_pair_reports,
    write_summary_md,
)

app = typer.Typer(add_completion=False, no_args_is_help=False, help=__doc__)
console = Console()


@app.command()
def main(
    dataset: Path = typer.Option(DATASET_PATH, "--dataset"),
    pairs: Path = typer.Option(CANDIDATE_PAIRS_PATH, "--pairs"),
    axes: Path = typer.Option(SECTION_AXES_AUTO_PATH, "--axes"),
    results_dir: Path = typer.Option(QWEN_RESULTS_DIR, "--results-dir"),
    out_dir: Path = typer.Option(REPORTS_DIR, "--out-dir"),
) -> None:
    if not pairs.exists():
        raise typer.BadParameter(f"pairs не найдены: {pairs}")
    if not axes.exists():
        raise typer.BadParameter(f"axes не найдены: {axes}")

    out_dir.mkdir(parents=True, exist_ok=True)

    candidates = [CandidatePair.model_validate(obj) for obj in iter_jsonl(pairs)]
    axes_list = [SectionAxis.model_validate(obj) for obj in iter_jsonl(axes)]

    pair_reviews = load_pair_reviews(results_dir / "pairs.jsonl")
    axis_reviews = load_axis_reviews(results_dir / "sections.jsonl")

    merged_pairs = merge_pairs(candidates, pair_reviews)
    merged_axes_list = merge_axes(axes_list, axis_reviews)

    counts = write_pair_reports(merged_pairs, out_dir)
    axis_count = write_axes_report(merged_axes_list, out_dir)

    total_tests = sum(1 for _ in iter_jsonl(dataset)) if dataset.exists() else 0
    write_summary_md(merged_pairs, merged_axes_list, out_dir, total_tests=total_tests)

    console.print(f"[green]OK[/] отчёты в {out_dir}")
    for fname, n in counts.items():
        console.print(f"  - {fname}: {n}")
    console.print(f"  - section_axis_hypotheses.csv: {axis_count}")
    console.print("  - summary.md")


if __name__ == "__main__":
    app()
