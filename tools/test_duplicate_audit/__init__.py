"""Ядро инструмента поиска дублей тестов TMS.

Пакет собирает в себе всё, что можно сделать локально без LLM:
нормализация текста, работа с деревом секций, эвристика осей секций,
кандидатные пары и сборка review-packs для Qwen CLI.
"""

__all__ = [
    "config",
    "models",
    "io_utils",
    "normalize",
    "section_tree",
    "infer_section_hypotheses",
    "candidate_generation",
    "review_pack_builder",
    "report_builder",
]
