# Skill `test-duplicate-audit`

Каталог skill'а для Qwen CLI. Структура:

```
test-duplicate-audit/
├── SKILL.md                  # главный entry-point skill'а
├── README.md                 # этот файл
├── prompts/
│   ├── infer_section_axes.md        # для sibling-групп секций
│   ├── review_candidate_pairs.md    # для пар тестов
│   └── triage_results.md            # для финальной сверки
├── schemas/
│   ├── section_axis.schema.json
│   └── pair_review.schema.json
└── examples/
    ├── example_section_group.json
    └── example_candidate_pair.json
```

## Как активировать

В сессии Qwen CLI скажи:

> «Используй skill test-duplicate-audit из `.qwen/skills/` и проанализируй
> файл `data/qwen_packs/pairs_to_review.md`. Сохрани результаты в
> `data/qwen_results/pairs.jsonl` по одному JSON-объекту на строку.»

## Формат ответов

Всегда **JSONL**. Один JSON-объект на строку, без комментариев. Поля —
в точности как в схемах. Русский текст — без escape.

## Типичные ошибки

- Отвечать прозой вместо JSON → ломает `merge_qwen_results.py`.
- Путать `LIKELY_DUPLICATE` и `RELATED_NOT_DUPLICATE` при business-variant
  разнице → см. SKILL.md правило #1.
- Возвращать не тот `test_a_id`/`test_b_id` из pack'а → merge не найдёт
  пару.
