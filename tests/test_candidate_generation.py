"""Unit-тесты для генерации кандидатных пар."""

from __future__ import annotations

from tools.test_duplicate_audit.candidate_generation import generate_candidate_pairs
from tools.test_duplicate_audit.config import THRESHOLDS, WEIGHTS
from tools.test_duplicate_audit.infer_section_hypotheses import infer_all
from tools.test_duplicate_audit.models import TestItem, Verdict
from tools.test_duplicate_audit.normalize import normalize_section_name, normalize_title
from tools.test_duplicate_audit.section_tree import SectionTree, split_section_path


def _item(test_id: str, title: str, path: str) -> TestItem:
    parts = split_section_path(path, "/")
    title_norm, title_tokens = normalize_title(title)
    section_tokens: list[str] = []
    for p in parts:
        _, toks = normalize_section_name(p)
        section_tokens.extend(toks)
    return TestItem(
        test_id=test_id,
        title=title,
        full_section_path=path,
        section_path_parts=parts,
        title_norm=title_norm,
        title_tokens=title_tokens,
        section_tokens=section_tokens,
    )


def _run(items: list[TestItem]) -> list:
    tree = SectionTree.build(items, sep="/")
    axes = infer_all(tree)
    variant_tokens = tree.derive_variant_tokens()
    return generate_candidate_pairs(
        items,
        tree=tree,
        axes=axes,
        thresholds=THRESHOLDS,
        weights=WEIGHTS,
        variant_tokens=variant_tokens,
    )


def test_same_section_rephrase_is_likely_duplicate() -> None:
    # Берём большой sample, чтобы TF-IDF имел стабильный контекст.
    items = [
        _item("T-1", "Перевод по номеру телефона внутри банка", "Банк/Переводы/По телефону"),
        _item("T-2", "Перевод по номеру телефона внутри банка получателю", "Банк/Переводы/По телефону"),
        _item("T-3", "Перевод по номеру телефона в другой банк", "Банк/Переводы/По телефону/Межбанк"),
        _item("T-4", "Перевод по карте", "Банк/Переводы/По карте"),
        _item("T-5", "Перевод по реквизитам юрлицу", "Банк/Переводы/По реквизитам"),
        _item("T-6", "Смена пароля пользователя", "Профиль/Безопасность"),
        _item("T-7", "Просмотр истории операций", "Операции/История"),
        _item("T-8", "Создание вклада", "Вклады/Создание"),
        _item("T-9", "Оформление кредита", "Кредиты/Оформление"),
        _item("T-10", "Поиск операций по дате", "Операции/Поиск"),
    ]
    pairs = _run(items)
    target = [p for p in pairs if {p.test_a_id, p.test_b_id} == {"T-1", "T-2"}]
    assert target, "пара T-1/T-2 не попала в кандидаты"
    # Т-1 и Т-2 — перефраз в одной секции, без variant-конфликта: должны
    # классифицироваться как дубль (LIKELY или POSSIBLE).
    assert target[0].auto_verdict in {Verdict.LIKELY_DUPLICATE, Verdict.POSSIBLE_DUPLICATE}
    assert target[0].score.same_section is True


def test_variant_conflict_is_related_not_duplicate() -> None:
    # Названия близки лексически, но отличаются бизнес-вариантом (телефон/карта).
    items = [
        _item("T-1", "Перевод денег по номеру телефона получателю", "Банк/Переводы/По телефону"),
        _item("T-2", "Перевод денег по карте получателю", "Банк/Переводы/По карте"),
        _item("T-3", "Перевод денег по реквизитам получателю", "Банк/Переводы/По реквизитам"),
        _item("T-4", "Перевод по номеру телефона контрагенту", "Банк/Переводы/По телефону"),
        # шум
        _item("T-5", "Смена пароля пользователя", "Профиль/Безопасность"),
        _item("T-6", "Просмотр истории операций", "Операции/История"),
        _item("T-7", "Создание вклада", "Вклады/Создание"),
        _item("T-8", "Оформление кредита", "Кредиты/Оформление"),
    ]
    pairs = _run(items)
    phone_card = [p for p in pairs if {p.test_a_id, p.test_b_id} == {"T-1", "T-2"}]
    assert phone_card, "пара телефон/карта не попала в кандидаты"
    pair = phone_card[0]
    # Ключевое правило: разные бизнес-варианты → не дубль.
    assert pair.auto_verdict is Verdict.RELATED_NOT_DUPLICATE
    # Секционное отношение должно отразить переход по business-variant оси,
    # ИЛИ variant-конфликт в title.
    assert (
        pair.score.cross_business_variant
        or pair.score.variant_conflict
    )


def test_completely_different_tests_not_emitted() -> None:
    items = [
        _item("T-1", "Перевод по номеру телефона", "Банк/Переводы/По телефону"),
        _item("T-2", "Просмотр истории операций", "Операции/История"),
        _item("T-3", "Закрытие вклада", "Вклады/Закрытие"),
    ]
    pairs = _run(items)
    # между совершенно разными title пар быть не должно
    ids_unrelated = {"T-1", "T-2"}
    assert not any(
        {p.test_a_id, p.test_b_id} == ids_unrelated for p in pairs
    )
