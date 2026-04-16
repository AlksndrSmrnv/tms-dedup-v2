"""scripts/generate_candidate_pairs.py — шаг 3 пайплайна.

Генерирует кандидатные пары с авто-вердиктом и помечает пограничные на
ревью Qwen.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from tools.test_duplicate_audit.candidate_generation import generate_candidate_pairs
from tools.test_duplicate_audit.config import (
    CANDIDATE_PAIRS_PATH,
    DATASET_PATH,
    DEFAULT_SECTION_SEP,
    SECTION_AXES_AUTO_PATH,
    THRESHOLDS,
    WEIGHTS,
)
from tools.test_duplicate_audit.io_utils import iter_jsonl, write_jsonl
from tools.test_duplicate_audit.models import SectionAxis, TestItem
from tools.test_duplicate_audit.section_tree import SectionTree

app = typer.Typer(add_completion=False, no_args_is_help=False, help=__doc__)
console = Console()


@app.command()
def main(
    dataset: Path = typer.Option(DATASET_PATH, "--dataset"),
    axes: Path = typer.Option(SECTION_AXES_AUTO_PATH, "--axes"),
    output: Path = typer.Option(CANDIDATE_PAIRS_PATH, "--output"),
    section_sep: str = typer.Option(DEFAULT_SECTION_SEP, "--section-sep"),
    top_k: int = typer.Option(
        THRESHOLDS.top_k_neighbors, "--top-k", help="Сколько соседей на тест (блокирование)"
    ),
) -> None:
    if not dataset.exists():
        raise typer.BadParameter(f"dataset не найден: {dataset}")
    if not axes.exists():
        raise typer.BadParameter(f"section axes не найдены: {axes}")

    items = [TestItem.model_validate(obj) for obj in iter_jsonl(dataset)]
    axes_list = [SectionAxis.model_validate(obj) for obj in iter_jsonl(axes)]
    tree = SectionTree.build(items, sep=section_sep)
    variant_tokens = tree.derive_variant_tokens()

    console.log(
        f"Тестов: {len(items)}; осей: {len(axes_list)}; variant-токенов: {len(variant_tokens)}"
    )

    thresholds = THRESHOLDS if top_k == THRESHOLDS.top_k_neighbors else THRESHOLDS.__class__(
        top_k_neighbors=top_k
    )
    pairs = generate_candidate_pairs(
        items,
        tree=tree,
        axes=axes_list,
        thresholds=thresholds,
        weights=WEIGHTS,
        variant_tokens=variant_tokens,
    )

    ct: Counter[str] = Counter(p.auto_verdict.value for p in pairs)
    review_n = sum(1 for p in pairs if p.needs_qwen_review)

    table = Table(title="Кандидатные пары (авто-разметка)")
    table.add_column("Вердикт")
    table.add_column("Кол-во", justify="right")
    for k in [
        "LIKELY_DUPLICATE",
        "POSSIBLE_DUPLICATE",
        "RELATED_NOT_DUPLICATE",
    ]:
        table.add_row(k, str(ct.get(k, 0)))
    table.add_row("[yellow]нужен Qwen review[/]", str(review_n))
    console.print(table)

    n = write_jsonl(output, pairs)
    console.print(f"[green]OK[/] записано {n} пар → {output}")


if __name__ == "__main__":
    app()
