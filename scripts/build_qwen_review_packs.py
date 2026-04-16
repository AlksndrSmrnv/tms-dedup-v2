"""scripts/build_qwen_review_packs.py — шаг 4 пайплайна.

Создаёт два review-pack'а для интерактивной работы с Qwen CLI:

- `data/qwen_packs/section_axes_review.jsonl` + `.md`
- `data/qwen_packs/pairs_to_review.jsonl` + `.md`
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from tools.test_duplicate_audit.config import (
    CANDIDATE_PAIRS_PATH,
    QWEN_PACKS_DIR,
    SECTION_AXES_AUTO_PATH,
)
from tools.test_duplicate_audit.infer_section_hypotheses import filter_for_review
from tools.test_duplicate_audit.io_utils import iter_jsonl
from tools.test_duplicate_audit.models import CandidatePair, SectionAxis
from tools.test_duplicate_audit.review_pack_builder import (
    build_pairs_pack,
    build_section_axes_pack,
)

app = typer.Typer(add_completion=False, no_args_is_help=False, help=__doc__)
console = Console()


@app.command()
def main(
    axes: Path = typer.Option(SECTION_AXES_AUTO_PATH, "--axes"),
    pairs: Path = typer.Option(CANDIDATE_PAIRS_PATH, "--pairs"),
    out_dir: Path = typer.Option(QWEN_PACKS_DIR, "--out-dir"),
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    if not axes.exists():
        raise typer.BadParameter(f"axes не найдены: {axes}")
    if not pairs.exists():
        raise typer.BadParameter(f"pairs не найдены: {pairs}")

    axes_list = [SectionAxis.model_validate(obj) for obj in iter_jsonl(axes)]
    pairs_list = [CandidatePair.model_validate(obj) for obj in iter_jsonl(pairs)]

    to_review_axes = filter_for_review(axes_list)
    n_ax, _ = build_section_axes_pack(
        to_review_axes,
        out_dir / "section_axes_review.jsonl",
        out_dir / "section_axes_review.md",
    )
    console.log(f"section axes pack: {n_ax} блоков")

    n_p, _ = build_pairs_pack(
        pairs_list,
        out_dir / "pairs_to_review.jsonl",
        out_dir / "pairs_to_review.md",
    )
    console.log(f"pairs pack: {n_p} пар")

    console.print(
        f"[green]OK[/] packs в {out_dir}. "
        "Открой в Qwen CLI и используй skill `test-duplicate-audit`."
    )


if __name__ == "__main__":
    app()
