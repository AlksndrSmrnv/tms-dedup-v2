"""Утилиты ввода/вывода: CSV/JSON/JSONL с атомарной записью.

Все артефакты пайплайна — в JSONL, чтобы можно было стримить большие
объёмы и подключать несложные инструменты (jq, grep). CSV — только для
финальных отчётов, предназначенных для человека.
"""

from __future__ import annotations

import csv
import json
import os
import tempfile
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from pydantic import BaseModel


def ensure_dir(path: Path) -> None:
    """Создать директорию, если её нет. Идемпотентно."""
    path.mkdir(parents=True, exist_ok=True)


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    """Атомарная запись текста: сначала в tmp, затем rename.

    Это защищает от полу-записанных файлов при сбое скрипта.
    """
    ensure_dir(path.parent)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".part")
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as fh:
            fh.write(text)
        os.replace(tmp_path, path)
    except Exception:
        # Подчищаем tmp, если что-то пошло не так.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# --------------------------------------------------------------------------- #
# JSONL
# --------------------------------------------------------------------------- #


def iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    """Ленивое чтение JSONL по одной строке."""
    with path.open("r", encoding="utf-8") as fh:
        for line_num, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Битый JSON в {path}:{line_num}: {exc}") from exc


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return list(iter_jsonl(path))


def write_jsonl(path: Path, items: Iterable[dict[str, Any] | BaseModel]) -> int:
    """Атомарно сериализовать items в JSONL. Возвращает число записанных строк."""
    ensure_dir(path.parent)
    lines: list[str] = []
    count = 0
    for item in items:
        if isinstance(item, BaseModel):
            payload = item.model_dump(mode="json")
        else:
            payload = item
        lines.append(json.dumps(payload, ensure_ascii=False, sort_keys=False))
        count += 1
    atomic_write_text(path, "\n".join(lines) + ("\n" if lines else ""))
    return count


# --------------------------------------------------------------------------- #
# JSON
# --------------------------------------------------------------------------- #


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, data: Any, indent: int = 2) -> None:
    ensure_dir(path.parent)
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=indent) + "\n")


# --------------------------------------------------------------------------- #
# CSV
# --------------------------------------------------------------------------- #


def read_csv_rows(path: Path, encoding: str = "utf-8") -> list[dict[str, str]]:
    """Читает CSV в список dict. Разделитель определяется автоматически."""
    with path.open("r", encoding=encoding, newline="") as fh:
        sample = fh.read(4096)
        fh.seek(0)
        # По умолчанию запятая. Пробуем sniffer, но не падаем, если не определит.
        dialect: type[csv.Dialect] | csv.Dialect
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(fh, dialect=dialect)
        return [dict(row) for row in reader]


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fieldnames: list[str]) -> int:
    ensure_dir(path.parent)
    count = 0
    # Собираем в память, затем атомарно пишем.
    buf: list[str] = []
    buf.append(",".join(_csv_quote(name) for name in fieldnames))
    for row in rows:
        vals = [_csv_quote(_csv_render(row.get(name, ""))) for name in fieldnames]
        buf.append(",".join(vals))
        count += 1
    atomic_write_text(path, "\n".join(buf) + ("\n" if buf else ""))
    return count


def _csv_render(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "; ".join(str(v) for v in value)
    return str(value)


def _csv_quote(value: str) -> str:
    """Минимальное корректное CSV-экранирование по RFC 4180."""
    if any(ch in value for ch in [",", "\"", "\n", "\r"]):
        escaped = value.replace("\"", "\"\"")
        return f'"{escaped}"'
    return value


__all__ = [
    "ensure_dir",
    "atomic_write_text",
    "iter_jsonl",
    "read_jsonl",
    "write_jsonl",
    "read_json",
    "write_json",
    "read_csv_rows",
    "write_csv",
]
