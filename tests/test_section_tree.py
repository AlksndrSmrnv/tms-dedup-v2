"""Unit-тесты построения дерева секций и эвристик."""

from __future__ import annotations

from tools.test_duplicate_audit.infer_section_hypotheses import classify_axis, infer_all
from tools.test_duplicate_audit.models import AxisType, TestItem
from tools.test_duplicate_audit.normalize import normalize_section_name, normalize_title
from tools.test_duplicate_audit.section_tree import SectionTree, split_section_path


def _make_item(test_id: str, title: str, path: str) -> TestItem:
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


def test_split_section_path_basic() -> None:
    assert split_section_path("A/B/C", "/") == ["A", "B", "C"]
    assert split_section_path("A / B / C", "/") == ["A", "B", "C"]
    assert split_section_path("", "/") == []
    assert split_section_path("A", "/") == ["A"]


def test_tree_inserts_tests_into_leaves() -> None:
    items = [
        _make_item("1", "Перевод по телефону", "Банк/Переводы/По телефону"),
        _make_item("2", "Перевод по карте", "Банк/Переводы/По карте"),
    ]
    tree = SectionTree.build(items, sep="/")
    node = tree.root.children["Банк"].children["Переводы"]
    assert "По телефону" in node.children
    assert "По карте" in node.children
    all_under_parent = node.all_tests()
    assert len(all_under_parent) == 2


def test_business_variant_detected() -> None:
    items = [
        _make_item("1", "Перевод по номеру телефона", "Банк/Переводы/По телефону"),
        _make_item("2", "Отправка перевода на номер мобильного", "Банк/Переводы/По телефону"),
        _make_item("3", "Перевод по карте получателя", "Банк/Переводы/По карте"),
        _make_item("4", "Отправка перевода на карту", "Банк/Переводы/По карте"),
        _make_item("5", "Перевод по реквизитам", "Банк/Переводы/По реквизитам"),
    ]
    tree = SectionTree.build(items, sep="/")
    axes = infer_all(tree)
    # ищем гипотезу для "Банк/Переводы"
    translations = [a for a in axes if a.parent_section == "Банк/Переводы"]
    assert translations, "не найдена гипотеза для Переводов"
    axis = translations[0]
    assert axis.axis_type is AxisType.BUSINESS_VARIANT


def test_tech_group_detected() -> None:
    items = [
        _make_item("1", "A", "Root/Регресс/Переводы"),
        _make_item("2", "B", "Root/Смоук/Переводы"),
        _make_item("3", "C", "Root/Ручные/Переводы"),
    ]
    tree = SectionTree.build(items, sep="/")
    axes = infer_all(tree)
    roots = [a for a in axes if a.parent_section == "Root"]
    assert roots
    assert roots[0].axis_type is AxisType.TECH_GROUP


def test_derive_variant_tokens_auto_extends() -> None:
    items = [
        _make_item("1", "Перевод по токену X", "Банк/Переводы/По токену"),
        _make_item("2", "Перевод по токену Y", "Банк/Переводы/По токену"),
        _make_item("3", "Перевод по карте", "Банк/Переводы/По карте"),
        _make_item("4", "Перевод по номеру телефона", "Банк/Переводы/По телефону"),
    ]
    tree = SectionTree.build(items, sep="/")
    derived = tree.derive_variant_tokens()
    # seed содержит "телефон" и "карта"; "токен" должно автоматически подтянуться
    assert "телефон" in derived
    # "токен" — не в seed; проверим что авто-расширение сработало
    # (после лёгкого стемминга это может быть "токен" или "ток")
    assert any(t.startswith("токен") or t.startswith("ток") for t in derived)
