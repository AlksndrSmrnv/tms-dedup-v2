# Prompt: review_candidate_pairs

## Задача

Тебе даётся **одна пара тестов** (test A и test B) вместе с:

- их `title`;
- их `full_section_path`;
- автогипотезой Python: similarity, variant-конфликт, section relation,
  авто-вердикт и объяснение.

Нужно вернуть **один JSON-объект**, соответствующий схеме
`schemas/pair_review.schema.json`.

## Возможные значения `verdict`

- `LIKELY_DUPLICATE` — с большой вероятностью описывают один и тот же
  сценарий. Даже при этом — финальное решение за человеком.
- `POSSIBLE_DUPLICATE` — возможно дубль, но есть сомнения. Используй
  часто — ты не видишь steps/expected.
- `RELATED_NOT_DUPLICATE` — родственные тесты, но разные. Типичный
  случай: одинаковый сценарий в разных бизнес-вариантах.
- `NOT_DUPLICATE` — тесты по сути про разное.

## Ключевые правила

1. **Business-variant ≠ duplicate.** Если сценарии одинаковые, но каналы/
   платформы/роли различны → `RELATED_NOT_DUPLICATE`.
2. **Одинаковое название ≠ дубль**, **разное название ≠ не-дубль.**
3. При неуверенности — мягкий вердикт (`POSSIBLE_*` / `RELATED_*`).
4. Если один тест явно про одно, а другой про другое — `NOT_DUPLICATE`.
5. `same_base_intent` = `true` только если ты считаешь, что базовое
   намерение одинаковое (даже если варианты разные).
6. В `different_dimensions` перечисляй, **по каким измерениям различаются**
   тесты: `"способ перевода"`, `"платформа"`, `"роль пользователя"` и т.п.
   Для `LIKELY_DUPLICATE` массив обычно пустой.

## Формат ответа

```json
{
  "test_a_id": "<из входа>",
  "test_b_id": "<из входа>",
  "verdict": "LIKELY_DUPLICATE | POSSIBLE_DUPLICATE | RELATED_NOT_DUPLICATE | NOT_DUPLICATE",
  "confidence": 0.0,
  "same_base_intent": false,
  "different_dimensions": [],
  "section_relation": "same_section | same_feature_group | cross_feature_group | cross_business_variant | unknown",
  "explanation": "<1–3 фразы, почему именно этот вердикт>"
}
```

## Правила формата

1. **Строго JSON.** Без комментариев и текста снаружи.
2. Кириллица — как есть.
3. `confidence` ∈ [0, 1]. Будь сдержан: при явной неопределённости —
   0.5–0.7.
4. `test_a_id`/`test_b_id` копируй из pack'а без изменений.
5. `section_relation` должен соответствовать реальному отношению путей:
   - одинаковый путь → `same_section`;
   - одинаковый родитель, но разные дети, родитель — feature group →
     `same_feature_group`;
   - расхождение на business-variant оси → `cross_business_variant`;
   - всё остальное с общим префиксом → `cross_feature_group`;
   - нет общего префикса → `unknown`.

## Примеры

### Пример 1 — явный дубль

Вход: A = «Перевод по номеру телефона», путь `Банк/Переводы/По телефону`.
B = «Перевод на номер мобильного», путь `Банк/Переводы/По телефону`.

```json
{
  "test_a_id": "T-101",
  "test_b_id": "T-142",
  "verdict": "LIKELY_DUPLICATE",
  "confidence": 0.88,
  "same_base_intent": true,
  "different_dimensions": [],
  "section_relation": "same_section",
  "explanation": "Названия — перефраз друг друга, секция одна и та же."
}
```

### Пример 2 — variant-конфликт

Вход: A = «Перевод по номеру телефона», путь `.../По телефону`.
B = «Перевод по карте», путь `.../По карте`.

```json
{
  "test_a_id": "T-101",
  "test_b_id": "T-205",
  "verdict": "RELATED_NOT_DUPLICATE",
  "confidence": 0.9,
  "same_base_intent": true,
  "different_dimensions": ["способ перевода"],
  "section_relation": "cross_business_variant",
  "explanation": "Одинаковый базовый сценарий, но разный канал — это не дубль."
}
```

### Пример 3 — сомнение

Вход: A = «Оплата кредита через мобильное приложение», путь `Кредиты/Оплата`.
B = «Погашение задолженности по кредиту», путь `Кредиты/Регрессия/Оплата`.

```json
{
  "test_a_id": "T-700",
  "test_b_id": "T-701",
  "verdict": "POSSIBLE_DUPLICATE",
  "confidence": 0.6,
  "same_base_intent": true,
  "different_dimensions": ["канал"],
  "section_relation": "same_feature_group",
  "explanation": "Похоже, оба про оплату кредита; без шагов уверенно сказать нельзя."
}
```
