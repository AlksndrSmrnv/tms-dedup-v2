"""Построение дерева секций и анализ sibling-групп.

Дерево секций строится из `full_section_path`. Разделитель — настраиваемый,
по умолчанию `/`. Путь вида `Банк/Переводы/По телефону` даёт цепочку
узлов Банк → Переводы → По телефону.

Для каждого не-листового узла считаем sibling-группу (его непосредственные дети)
и агрегируем по ней статистики, которые используются эвристиками.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Iterable

from .config import SEED_TECH_SECTION_TOKENS, SEED_VARIANT_TOKENS
from .models import TestItem
from .normalize import normalize_section_name


def split_section_path(path: str, sep: str = "/") -> list[str]:
    """Разбить full_section_path на части с удалением пустых и тримом пробелов."""
    if not path:
        return []
    return [part.strip() for part in path.split(sep) if part and part.strip()]


@dataclass
class SectionNode:
    """Узел дерева секций.

    `key` — путь от корня до узла, '/'-разделён. Используется как стабильный id.
    """

    name: str
    key: str
    parent: "SectionNode | None" = None
    children: dict[str, "SectionNode"] = field(default_factory=dict)
    tests: list[TestItem] = field(default_factory=list)

    @property
    def is_leaf(self) -> bool:
        return not self.children

    def all_tests(self) -> list[TestItem]:
        """Все тесты в поддереве (включая потомков)."""
        acc = list(self.tests)
        for child in self.children.values():
            acc.extend(child.all_tests())
        return acc


@dataclass
class SiblingGroupStats:
    """Агрегированные показатели sibling-группы (один parent-узел)."""

    parent_key: str
    parent_name: str
    child_names: list[str]
    child_keys: list[str]
    child_name_overlap: float
    title_pattern_overlap: float
    variant_token_hits: int
    tech_token_hits: int
    distinctive_tokens: dict[str, list[str]]  # child_key -> уникальные для него токены
    per_child_test_count: dict[str, int]

    @property
    def child_count(self) -> int:
        return len(self.child_keys)


class SectionTree:
    """Корень дерева секций + вспомогательные методы."""

    def __init__(self, sep: str = "/"):
        self.sep = sep
        self.root = SectionNode(name="", key="")

    # ------------------------------------------------------------------ #
    # Построение дерева
    # ------------------------------------------------------------------ #

    def insert(self, item: TestItem) -> None:
        """Добавить тест в соответствующий лист."""
        parts = item.section_path_parts or split_section_path(item.full_section_path, self.sep)
        node = self.root
        acc_key = ""
        for part in parts:
            acc_key = f"{acc_key}{self.sep}{part}" if acc_key else part
            if part not in node.children:
                node.children[part] = SectionNode(name=part, key=acc_key, parent=node)
            node = node.children[part]
        node.tests.append(item)

    @classmethod
    def build(cls, items: Iterable[TestItem], sep: str = "/") -> "SectionTree":
        tree = cls(sep=sep)
        for it in items:
            tree.insert(it)
        return tree

    # ------------------------------------------------------------------ #
    # Обход
    # ------------------------------------------------------------------ #

    def iter_nodes(self) -> Iterable[SectionNode]:
        stack = [self.root]
        while stack:
            node = stack.pop()
            yield node
            stack.extend(node.children.values())

    def iter_sibling_groups(self) -> Iterable[SectionNode]:
        """Вернуть parent-узлы, у которых ≥2 детей."""
        for node in self.iter_nodes():
            if len(node.children) >= 2:
                yield node

    # ------------------------------------------------------------------ #
    # Статистика sibling-группы
    # ------------------------------------------------------------------ #

    def compute_stats(self, parent: SectionNode) -> SiblingGroupStats:
        child_nodes = list(parent.children.values())
        child_name_tokens: dict[str, set[str]] = {}
        per_child_test_count: dict[str, int] = {}
        per_child_title_tokens: dict[str, Counter[str]] = {}

        for child in child_nodes:
            _, name_tokens = normalize_section_name(child.name)
            child_name_tokens[child.key] = set(name_tokens)
            tests = child.all_tests()
            per_child_test_count[child.key] = len(tests)
            counter: Counter[str] = Counter()
            for t in tests:
                counter.update(t.title_tokens)
            per_child_title_tokens[child.key] = counter

        # Overlap имён детей
        child_name_overlap = _jaccard_multi(list(child_name_tokens.values()))

        # Overlap топ-токенов заголовков детей
        top_token_sets: list[set[str]] = []
        for counter in per_child_title_tokens.values():
            # top N токенов в titles
            top = {tok for tok, _ in counter.most_common(20)}
            top_token_sets.append(top)
        title_pattern_overlap = _jaccard_multi(top_token_sets)

        # Variant / tech hits — по токенам имён секций
        variant_hits = 0
        tech_hits = 0
        for toks in child_name_tokens.values():
            if toks & SEED_VARIANT_TOKENS:
                variant_hits += 1
            if toks & SEED_TECH_SECTION_TOKENS:
                tech_hits += 1

        # Distinctive tokens: токены, присутствующие у одного ребёнка и отсутствующие у других
        distinctive: dict[str, list[str]] = {}
        all_union: Counter[str] = Counter()
        for toks in child_name_tokens.values():
            all_union.update(toks)
        for key, toks in child_name_tokens.items():
            distinctive[key] = sorted(t for t in toks if all_union[t] == 1)

        return SiblingGroupStats(
            parent_key=parent.key,
            parent_name=parent.name or "<root>",
            child_names=[c.name for c in child_nodes],
            child_keys=[c.key for c in child_nodes],
            child_name_overlap=child_name_overlap,
            title_pattern_overlap=title_pattern_overlap,
            variant_token_hits=variant_hits,
            tech_token_hits=tech_hits,
            distinctive_tokens=distinctive,
            per_child_test_count=per_child_test_count,
        )

    # ------------------------------------------------------------------ #
    # Выделение variant-токенов по всему дереву (автообогащение seed-словаря)
    # ------------------------------------------------------------------ #

    def derive_variant_tokens(self) -> set[str]:
        """Вернуть расширенный набор variant-токенов.

        Алгоритм: собираем distinctive-токены со всех sibling-групп,
        у которых есть минимум один seed-variant hit ИЛИ высокий title overlap
        при низком name overlap (характерно для business variant).
        Это даёт автоматическое расширение без хардкода словаря.
        """
        acc: set[str] = set(SEED_VARIANT_TOKENS)
        for parent in self.iter_sibling_groups():
            stats = self.compute_stats(parent)
            looks_like_variant = (
                stats.variant_token_hits >= 1
                or (stats.title_pattern_overlap >= 0.35 and stats.child_name_overlap <= 0.25)
            )
            if not looks_like_variant:
                continue
            for toks in stats.distinctive_tokens.values():
                for t in toks:
                    # не подхватываем слишком общие/короткие токены
                    if len(t) >= 3:
                        acc.add(t)
        return acc

    # ------------------------------------------------------------------ #
    # Поиск parent sibling-группы для двух секций
    # ------------------------------------------------------------------ #

    def find_common_parent(
        self, path_a: list[str], path_b: list[str]
    ) -> tuple[str, int]:
        """Вернуть (key_общего_родителя, длина_общего_префикса)."""
        common = 0
        for a, b in zip(path_a, path_b):
            if a == b:
                common += 1
            else:
                break
        parent_parts = path_a[:common]
        parent_key = self.sep.join(parent_parts) if parent_parts else ""
        return parent_key, common


# --------------------------------------------------------------------------- #
# Вспомогательные функции
# --------------------------------------------------------------------------- #


def _jaccard_multi(sets: list[set[str]]) -> float:
    """Средний попарный жаккар по списку наборов токенов."""
    if len(sets) < 2:
        return 0.0
    total = 0.0
    n = 0
    for i in range(len(sets)):
        for j in range(i + 1, len(sets)):
            a, b = sets[i], sets[j]
            if not a and not b:
                continue
            union = a | b
            if not union:
                continue
            total += len(a & b) / len(union)
            n += 1
    return total / n if n else 0.0


__all__ = [
    "split_section_path",
    "SectionNode",
    "SiblingGroupStats",
    "SectionTree",
]
