"""scripts/build_dataset.py — шаг 1 пайплайна.

Читает CSV/JSON с полями `test_id`, `title`, `full_section_path`, применяет
нормализацию и выдаёт каноничный JSONL в `data/dataset.jsonl`.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.progress import track

from tools.test_duplicate_audit.config import DATASET_PATH, DEFAULT_SECTION_SEP
from tools.test_duplicate_audit.io_utils import read_csv_rows, read_json, write_jsonl
from tools.test_duplicate_audit.models import TestItem
from tools.test_duplicate_audit.normalize import normalize_section_name, normalize_title
from tools.test_duplicate_audit.section_tree import split_section_path

app = typer.Typer(add_completion=False, no_args_is_help=True, help=__doc__)
console = Console()


REQUIRED_FIELDS = {"test_id", "title", "full_section_path"}


def _load_rows(path: Path) -> list[dict[str, str]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return read_csv_rows(path)
    if suffix in {".json", ".jsonl"}:
        data = read_json(path) if suffix == ".json" else [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if isinstance(data, dict):
            # некоторые экспорты TMS заворачивают массив в { "items": [...] }
            for key in ("items", "tests", "data"):
                if key in data and isinstance(data[key], list):
                    return [dict(row) for row in data[key]]
            raise typer.BadParameter(
                f"Не нашёл массив тестов в JSON {path}. Ожидается массив или "
                "объект с ключом items/tests/data."
            )
        if isinstance(data, list):
            return [dict(row) for row in data]
        raise typer.BadParameter(f"Неподдерживаемая структура JSON в {path}")
    raise typer.BadParameter(f"Неизвестный формат: {suffix}. Поддерживаются .csv, .json, .jsonl")


def _build_item(row: dict[str, str], section_sep: str) -> TestItem:
    missing = REQUIRED_FIELDS - set(row)
    if missing:
        raise ValueError(f"Строке не хватает полей: {missing}. Строка: {row}")
    title = str(row["title"]).strip()
    full_path = str(row["full_section_path"]).strip()
    parts = split_section_path(full_path, section_sep)
    title_norm, title_tokens = normalize_title(title)
    section_tokens: list[str] = []
    for part in parts:
        _, toks = normalize_section_name(part)
        section_tokens.extend(toks)
    return TestItem(
        test_id=row["test_id"],
        title=title,
        full_section_path=full_path,
        section_path_parts=parts,
        title_norm=title_norm,
        title_tokens=title_tokens,
        section_tokens=section_tokens,
    )


@app.command()
def main(
    input: Path = typer.Option(..., "--input", "-i", help="CSV/JSON экспорт TMS"),
    output: Path = typer.Option(DATASET_PATH, "--output", "-o", help="Куда писать JSONL"),
    section_sep: str = typer.Option(
        DEFAULT_SECTION_SEP, "--section-sep", help="Разделитель секций в full_section_path"
    ),
) -> None:
    if not input.exists():
        raise typer.BadParameter(f"Файл не найден: {input}")

    console.log(f"Читаю {input}")
    rows = _load_rows(input)
    console.log(f"Загружено строк: {len(rows)}")

    items: list[TestItem] = []
    for row in track(rows, description="Нормализация..."):
        try:
            items.append(_build_item(row, section_sep))
        except Exception as exc:  # noqa: BLE001
            console.print(f"[yellow]Пропускаю строку: {exc}[/]")

    count = write_jsonl(output, items)
    console.print(f"[green]OK[/] записано {count} тестов → {output}")


if __name__ == "__main__":
    app()
