"""scripts/infer_section_hypotheses.py — шаг 2 пайплайна.

Строит дерево секций и выдаёт гипотезы по sibling-группам.
Результат: JSONL со всеми гипотезами (для дальнейших шагов) и статистикой.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from tools.test_duplicate_audit.config import (
    DATASET_PATH,
    DEFAULT_SECTION_SEP,
    SECTION_AXES_AUTO_PATH,
)
from tools.test_duplicate_audit.infer_section_hypotheses import infer_all
from tools.test_duplicate_audit.io_utils import iter_jsonl, write_jsonl
from tools.test_duplicate_audit.models import TestItem
from tools.test_duplicate_audit.section_tree import SectionTree

app = typer.Typer(add_completion=False, no_args_is_help=False, help=__doc__)
console = Console()


@app.command()
def main(
    dataset: Path = typer.Option(DATASET_PATH, "--dataset", help="JSONL с нормализованными тестами"),
    output: Path = typer.Option(
        SECTION_AXES_AUTO_PATH, "--output", help="Куда писать JSONL гипотез"
    ),
    section_sep: str = typer.Option(DEFAULT_SECTION_SEP, "--section-sep"),
) -> None:
    if not dataset.exists():
        raise typer.BadParameter(f"dataset не найден: {dataset}. Сначала build_dataset.py")

    items = [TestItem.model_validate(obj) for obj in iter_jsonl(dataset)]
    console.log(f"Загружено тестов: {len(items)}")

    tree = SectionTree.build(items, sep=section_sep)
    axes = infer_all(tree)

    from collections import Counter

    ct: Counter[str] = Counter(a.axis_type.value for a in axes)
    table = Table(title="Гипотезы по осям секций")
    table.add_column("Тип")
    table.add_column("Кол-во", justify="right")
    for k in ["BUSINESS_VARIANT", "FEATURE_GROUP", "TECH_GROUP", "UNKNOWN"]:
        table.add_row(k, str(ct.get(k, 0)))
    console.print(table)

    n = write_jsonl(output, axes)
    console.print(f"[green]OK[/] записано {n} гипотез → {output}")


if __name__ == "__main__":
    app()
