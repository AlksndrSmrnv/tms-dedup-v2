# tms-dedup-v2

Локальный инструмент поиска **вероятных дублей тестов** в модели TMS / Test IT
на ~2500 тестов. Использует только `title` и `full_section_path`.
Никаких внешних LLM API, embeddings API, ручной разметки секций и тяжёлой
инфраструктуры.

Проект состоит из двух слоёв:

- **Python-пайплайн** (каталог `tools/test_duplicate_audit/`, скрипты в
  `scripts/`) — нормализация, построение дерева секций, эвристика осей,
  TF-IDF + RapidFuzz кандидатная генерация, сборка review-packs и финальные
  отчёты.
- **Qwen CLI skill** (каталог `.qwen/skills/test-duplicate-audit/`) —
  интерактивное смысловое ревью пограничных случаев. Поскольку Qwen CLI не
  headless, Python **не вызывает его напрямую**, а готовит review-packs
  (`JSONL` + `Markdown`), которые пользователь открывает в интерактивной
  сессии.

Вердикты — с уровнями уверенности:

- `LIKELY_DUPLICATE` — сильная гипотеза дубля (финальное решение всё равно
  за человеком);
- `POSSIBLE_DUPLICATE` — вероятно дубль, но есть сомнения;
- `RELATED_NOT_DUPLICATE` — родственные тесты (чаще всего — разные
  бизнес-варианты одного сценария);
- `NOT_DUPLICATE` — не дубль.

## Установка

Используется только **`uv`**.

```bash
uv sync
```

Это создаёт `.venv/` и ставит зависимости из `pyproject.toml`.

## Входные данные

CSV (или JSON/JSONL) с колонками:

- `test_id` — любой уникальный идентификатор (число или строка);
- `title` — название теста;
- `full_section_path` — путь до секции, по умолчанию через `/`.

Пример — в `data_samples/sample_tests.csv`.

## Полный workflow

```bash
# 1. Нормализация: CSV/JSON → data/dataset.jsonl
uv run python scripts/build_dataset.py --input data_samples/sample_tests.csv

# 2. Гипотезы по осям секций: data/section_axes.auto.jsonl
uv run python scripts/infer_section_hypotheses.py

# 3. Кандидатные пары + авто-вердикт: data/candidate_pairs.jsonl
uv run python scripts/generate_candidate_pairs.py

# 4. Review-packs для Qwen CLI: data/qwen_packs/*.{jsonl,md}
uv run python scripts/build_qwen_review_packs.py

# 5. (ручной шаг) В интерактивной сессии Qwen CLI:
#
#      > Используй skill test-duplicate-audit и проанализируй
#      > data/qwen_packs/pairs_to_review.md. Сохрани ответы в
#      > data/qwen_results/pairs.jsonl (по одному JSON на строку).
#
#    Аналогично для section_axes_review.md → data/qwen_results/sections.jsonl.

# 6. Валидация Qwen-ответов:
uv run python scripts/merge_qwen_results.py

# 7. Финальные отчёты в data/reports/
uv run python scripts/build_final_reports.py
```

Для быстрого прогона всей Python-части (без Qwen-ревью) есть
`make all`.

## Структура выходов

```
data/
├── dataset.jsonl                 # нормализованные тесты
├── section_axes.auto.jsonl       # авто-гипотезы осей секций
├── candidate_pairs.jsonl         # кандидатные пары + auto verdict
├── qwen_packs/
│   ├── section_axes_review.{jsonl,md}
│   └── pairs_to_review.{jsonl,md}
├── qwen_results/
│   ├── pairs.jsonl               # ← сохраняет пользователь после Qwen CLI
│   ├── sections.jsonl            # ← сохраняет пользователь после Qwen CLI
│   ├── pairs.normalized.jsonl    # создаётся merge_qwen_results.py
│   └── sections.normalized.jsonl
└── reports/
    ├── likely_duplicates.csv
    ├── possible_duplicates.csv
    ├── related_not_duplicates.csv
    ├── not_duplicates.csv
    ├── section_axis_hypotheses.csv
    └── summary.md
```

## Алгоритм вкратце

### 1. Нормализация (`tools/test_duplicate_audit/normalize.py`)

- lower + `ё→е` + NFKC;
- удаление пунктуации, схлопывание пробелов;
- токенизация;
- лёгкий эвристический стемминг русских окончаний (без pymorphy);
- фильтр noise-words (`тест`, `проверка`, …) и стоп-слов.

### 2. Дерево секций (`section_tree.py`)

Строится из `full_section_path` (разделитель настраивается `--section-sep`).
Для каждого parent-узла с ≥2 детьми считаем sibling-группу и её статистику:
overlap имён детей, overlap title-токенов, variant/tech-hits, distinctive-
токены.

### 3. Гипотезы по осям секций (`infer_section_hypotheses.py`)

Эвристики возвращают для каждой sibling-группы:

- `BUSINESS_VARIANT` — бизнес-варианты (телефон/карта/реквизиты);
- `FEATURE_GROUP` — разные фичи под общим зонтиком;
- `TECH_GROUP` — регресс/смоук/ручные/авто;
- `UNKNOWN` — уходит на ревью в Qwen CLI.

### 4. Вариантные токены

Seed-словарь минимальный (`телефон`, `карта`, `реквизит`, `сбп`, `web`,
`android`, `ios`, …) **+** авто-обогащение: distinctive-токены всех
sibling-групп, помеченных как BUSINESS_VARIANT, автоматически попадают в
variant-набор. Giant-словаря нет.

### 5. Кандидатные пары (`candidate_generation.py`)

- Блокирование через `NearestNeighbors(metric='cosine')` на char-n-gram
  TF-IDF, top-K=25 соседей на тест.
- Для каждой пары вычисляется:
  - char TF-IDF cosine,
  - word TF-IDF cosine,
  - RapidFuzz `token_set_ratio` (и `partial_ratio` для справки),
  - variant-conflict (есть ли у одной стороны variant-токен, которого нет
    у другой),
  - section relation (same/ same_feature_group / cross_business_variant / ...).
- Итог: `similarity = 0.55·char + 0.25·word + 0.20·token_set`. Penalty
  `-0.25` при cross_business_variant.
- Классификация:
  - variant-конфликт → `RELATED_NOT_DUPLICATE` (пограничные идут в pack);
  - cross_business_variant без конфликта в title → `RELATED_NOT_DUPLICATE`;
  - `similarity ≥ 0.88` → `LIKELY_DUPLICATE`;
  - `0.75 ≤ similarity < 0.88` → `POSSIBLE_DUPLICATE` (на ревью);
  - `0.60 ≤ similarity < 0.75` → `RELATED_NOT_DUPLICATE` (на ревью);
  - ниже — не эмитим.

### 6. Review-packs

Python **не запускает Qwen CLI**. Вместо этого создаются:

- `data/qwen_packs/pairs_to_review.jsonl` — машинно-читаемые записи;
- `data/qwen_packs/pairs_to_review.md` — человеко-читаемый pack с
  инструкциями, куда сохранять JSON-ответ.

Аналогично для sibling-секций.

### 7. Qwen-ревью

В интерактивной сессии Qwen CLI пользователь говорит «примени skill
test-duplicate-audit к этому pack'у». Skill (`.qwen/skills/
test-duplicate-audit/`) содержит:

- `SKILL.md` — главные правила интерпретации;
- `prompts/infer_section_axes.md`,
  `prompts/review_candidate_pairs.md`,
  `prompts/triage_results.md`;
- `schemas/*.schema.json` — строгие JSON-схемы ответов;
- `examples/*.json` — примеры входа/выхода.

Skill даёт **строго валидный JSON** согласно схемам. Пользователь сохраняет
его в `data/qwen_results/pairs.jsonl` / `sections.jsonl`.

### 8. Merge и отчёты

`merge_qwen_results.py` валидирует JSONL-ответы (битые — пропускает с
warning). `build_final_reports.py` собирает итог: Qwen-вердикт имеет
приоритет над авто-разметкой.

## Ограничения метода

- Используются **только** `title` и `full_section_path`. Steps, expected
  results, preconditions и params не видны. Любой вердикт — вероятностный.
- `LIKELY_DUPLICATE` не означает 100% дубль. Финальное решение — за
  человеком.
- Редкие бизнес-варианты, не похожие на seed-слова и не формирующие
  sibling-группу, могут быть пропущены. Решение: повторный прогон после
  правки дерева секций, либо добавление Qwen-ревью.
- Для очень больших моделей (десятки тысяч тестов) может потребоваться
  увеличить `--top-k` и/или ужесточить блокирование.
- Инструмент не делает авто-правок в TMS: только отчёты.

## Запуск тестов

```bash
uv run pytest
```

## Кастомизация

- Пороги: `tools/test_duplicate_audit/config.py` → `Thresholds`, `ScoreWeights`.
- Seed-словари: `SEED_VARIANT_TOKENS`, `SEED_TECH_SECTION_TOKENS`, `NOISE_WORDS`.
- Разделитель секций: CLI-флаг `--section-sep` у `build_dataset.py`,
  `infer_section_hypotheses.py`, `generate_candidate_pairs.py`.

## Лицензия

MIT.
