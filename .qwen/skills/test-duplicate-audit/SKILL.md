# Skill: test-duplicate-audit

## Назначение

Этот skill помогает пользователю интерактивно, в сессии Qwen CLI, размечать:

1. **Оси sibling-секций** — к какому типу относится группа дочерних секций
   одного родителя: `BUSINESS_VARIANT`, `FEATURE_GROUP`, `TECH_GROUP` или
   `UNKNOWN`.
2. **Кандидатные пары тестов** — является ли пара вероятным дублем:
   `LIKELY_DUPLICATE`, `POSSIBLE_DUPLICATE`, `RELATED_NOT_DUPLICATE`,
   `NOT_DUPLICATE`.

Skill работает с **review-packs**, которые заранее подготовлены Python-
пайплайном `tms-dedup-v2`. Packs лежат в `data/qwen_packs/` и содержат
как machine-readable JSONL, так и человеко-читаемый Markdown.

## Когда использовать

Активируй этот skill, когда пользователь просит:

- «проанализируй секции», «разметь оси секций», «какой тип у этих sibling»;
- «размети кандидатные пары тестов», «разбери пары на дубли»;
- открывает файл `data/qwen_packs/section_axes_review.{md,jsonl}`;
- открывает файл `data/qwen_packs/pairs_to_review.{md,jsonl}`;
- упоминает «test-duplicate-audit», «dedup», «TMS duplicate audit».

Skill НЕ предназначен для генерации новых тестов, правок в TMS или работы
со steps/expected — этих данных в pack'ах нет.

## Данные, которыми ты располагаешь

- `title` теста — короткое название.
- `full_section_path` — путь по дереву секций (обычно через `/`).
- Автогипотезы Python: similarity, score breakdown, section relation,
  variant-конфликт.

Тебе **не даны** шаги, ожидаемые результаты, предусловия или параметры.
Все вердикты — вероятностные. Никогда не утверждай 100% дубль.

## Критические правила интерпретации

1. **Business-variant ≠ duplicate.** Если два теста отличаются бизнес-
   вариантом (перевод по телефону vs по карте; СБП vs реквизиты; юрлицо
   vs физлицо), это **`RELATED_NOT_DUPLICATE`**, даже если названия почти
   совпадают.
2. **Одинаковое название ≠ дубль.** Если тесты лежат в разных секциях и
   секции указывают на разные варианты — это не дубль.
3. **Разное название ≠ не-дубль.** Перефразировки («Перевод по номеру
   телефона» и «Отправка на номер мобильного») могут быть дублями.
4. **Организационная секция (регресс/смоук/ручные/авто)** не делает
   тесты дублями или недублями. Смотри в `title`.
5. **В сомнении — мягкий вердикт.** При неуверенности выдавай
   `POSSIBLE_DUPLICATE` или `RELATED_NOT_DUPLICATE`, а не жёсткий
   `LIKELY_DUPLICATE`.
6. **Section relation.** Одинаковая секция → `same_section`. Общий
   родитель с тем же feature-group-ом → `same_feature_group`. Переход
   через business-variant → `cross_business_variant`. Иначе —
   `cross_feature_group` или `unknown`.

## Форматы ответа

Для каждого запроса возвращай **строго валидный JSON** согласно
соответствующей схеме:

- Оси секций: `schemas/section_axis.schema.json` — см.
  `prompts/infer_section_axes.md`.
- Пары тестов: `schemas/pair_review.schema.json` — см.
  `prompts/review_candidate_pairs.md`.
- Триаж и сводка по результатам: см. `prompts/triage_results.md`.

**Никогда** не добавляй комментарии вне JSON (`// ...`, текст после/до).
**Никогда** не эскейпь кириллицу.

## Workflow с review-pack

1. Пользователь открывает `data/qwen_packs/pairs_to_review.md` (или
   `.jsonl`) и говорит: «проанализируй pack по test-duplicate-audit».
2. Ты идёшь по блокам pack'а. На каждый блок выдаёшь **один** JSON-объект
   согласно `review_candidate_pairs.md`.
3. Итог — JSONL (по одному объекту на строку), пользователь сохраняет в
   `data/qwen_results/pairs.jsonl`.
4. Аналогично для `section_axes_review.md` → `data/qwen_results/sections.jsonl`.
5. Далее пользователь запускает `merge_qwen_results.py` и
   `build_final_reports.py`.

## Ограничения

- Без steps/expected можно ошибаться. Всегда честно объясняй причину
  вердикта и упоминай неопределённость в `explanation`.
- Variant-токены могут быть неполными — если видишь в названиях новые
  варианты (например, «по токену», «apple pay»), явно указывай их в
  `different_dimensions`.
- Не выдумывай test_id и parent_section — бери из pack'а.
